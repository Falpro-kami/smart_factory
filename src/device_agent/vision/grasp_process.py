from pathlib import Path
import sys

import cv2
import numpy as np
import open3d as o3d
import torch
from PIL import Image

CURRENT_DIR = Path(__file__).resolve().parent
GRASPNET_ROOT = CURRENT_DIR.parent / "graspnet-baseline"
GRASPNET_UTILS_DIR = GRASPNET_ROOT / "utils"
GRASPNET_MODELS_DIR = GRASPNET_ROOT / "models"
GRASPNET_DATASET_DIR = GRASPNET_ROOT / "dataset"
GRASPNET_API_DIR = GRASPNET_ROOT / "graspnetAPI"
for path in (
    GRASPNET_MODELS_DIR,
    GRASPNET_UTILS_DIR,
    GRASPNET_DATASET_DIR,
    GRASPNET_ROOT,
    GRASPNET_API_DIR,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from data_utils import CameraInfo, create_point_cloud_from_depth_image
from graspnet import GraspNet, pred_decode
from collision_detector import ModelFreeCollisionDetector

from graspnetAPI import GraspGroup


TABLE_OVERVIEW_POS = np.array([0.0, 0.0, 1.5], dtype=np.float32)
# MuJoCo quat 按 w, x, y, z 存储。
TABLE_OVERVIEW_QUAT = np.array([0.0, 0.0, 0.382683, 0.923879], dtype=np.float32)
# GraspNet/深度反投影采用相机前方为 +Z、图像向下为 +Y；
# MuJoCo 相机局部坐标采用光轴朝 -Z，因此显示到世界系前要做一次坐标约定转换。
CV_CAMERA_TO_MUJOCO_CAMERA = np.array([
    [1.0, 0.0, 0.0],
    [0.0, -1.0, 0.0],
    [0.0, 0.0, -1.0],
], dtype=np.float32)


def get_net():
    """
    加载训练好的 GraspNet 模型
    """
    net = GraspNet(input_feature_dim=0, 
                   num_view=300, 
                   num_angle=12, 
                   num_depth=4,
                   cylinder_radius=0.05, 
                   hmin=-0.02, 
                   hmax_list=[0.01, 0.02, 0.03, 0.04], 
                   is_training=False)
    net.to(torch.device('cuda:0' if torch.cuda.is_available() else 'cpu'))
    checkpoint = torch.load(CURRENT_DIR / "logs" / "log_rs" / "checkpoint-rs.tar")
    net.load_state_dict(checkpoint['model_state_dict'])
    net.eval()
    return net

def quat_wxyz_to_rotation_matrix(quat):
    quat = np.asarray(quat, dtype=np.float32)
    quat = quat / np.linalg.norm(quat)
    w, x, y, z = quat

    return np.array([
        [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)],
        [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)],
        [2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)],
    ], dtype=np.float32)

def refine_mask_with_depth(workspace_mask, depth):
    mask = workspace_mask > 0
    valid_depth_mask = np.isfinite(depth) & (depth > 0)
    refined_mask = mask & valid_depth_mask

    if not np.any(refined_mask):
        return valid_depth_mask
    return refined_mask


# ================= 数据处理并生成输入 ====================
def get_and_process_data(color_path, depth_path, mask_path):
    """
    根据给定的 RGB 图、深度图、掩码图（可以是 文件路径 或 NumPy 数组），生成输入点云及其它必要数据
    """
#---------------------------------------
    # 1. 加载 color（可能是路径，也可能是数组）
    if isinstance(color_path, str):
        color = np.array(Image.open(color_path), dtype=np.float32) / 255.0
    elif isinstance(color_path, np.ndarray):
        color = color_path.astype(np.float32)
        color /= 255.0
    else:
        raise TypeError("color_path 既不是字符串路径也不是 NumPy 数组！")

    # 2. 加载 depth（可能是路径，也可能是数组）
    if isinstance(depth_path, str):
        depth_file = Path(depth_path)
        if depth_file.suffix.lower() == ".npy":
            depth = np.load(depth_file).astype(np.float32)
        else:
            depth = cv2.imread(str(depth_file), cv2.IMREAD_UNCHANGED)
            if depth is None:
                raise FileNotFoundError(f"无法读取深度图: {depth_file}")
            depth = depth.astype(np.float32)
    elif isinstance(depth_path, np.ndarray):
        depth = depth_path.astype(np.float32)
    else:
        raise TypeError("depth_path 既不是字符串路径也不是 NumPy 数组！")

    # 3. 加载 mask（可能是路径，也可能是数组）
    if isinstance(mask_path, str):
        workspace_mask = np.array(Image.open(mask_path))
    elif isinstance(mask_path, np.ndarray):
        workspace_mask = mask_path
    else:
        raise TypeError("mask_path 既不是字符串路径也不是 NumPy 数组！")

    print("\n=== 尺寸验证 ===")
    print("深度图尺寸:", depth.shape)
    print("颜色图尺寸:", color.shape[:2])
    print("工作空间尺寸:", workspace_mask.shape)

    # 构造相机内参矩阵
    height = color.shape[0]
    width = color.shape[1]
    fovy_deg = 28.0
    fy = height / (2.0 * np.tan(np.deg2rad(fovy_deg) / 2.0))
    fx = fy
    c_x = width / 2.0
    c_y = height / 2.0
    intrinsic = np.array([
    [fx, 0.0, c_x],
    [0.0, fy, c_y],
    [0.0, 0.0, 1.0]
    ], dtype=np.float32)

    factor_depth = 1000.0  # depth.png 保存为毫米，点云计算时换算回米

    # 利用深度图生成点云 (H,W,3) 并保留组织结构
    camera = CameraInfo(width, height, intrinsic[0][0], intrinsic[1][1], intrinsic[0][2], intrinsic[1][2], factor_depth)
    cloud = create_point_cloud_from_depth_image(depth, camera, organized=True)
    # mask = depth < 2.0
    mask = refine_mask_with_depth(workspace_mask, depth)
    cloud_masked = cloud[mask]
    color_masked = color[mask]
    # print(f"mask过滤后的点云数量 (color_masked): {len(color_masked)}") # 在采样前打印原始过滤后的点数

    if len(cloud_masked) == 0:
        raise ValueError("掩码和深度过滤后没有有效点，请检查深度图、掩码或相机参数。")

    print("camera_z range:", float(np.min(cloud_masked[:, 2])), float(np.max(cloud_masked[:, 2])))

    NUM_POINT = 5000 # 10000或5000
    # 如果点数足够，随机采样NUM_POINT个点（不重复）
    if len(cloud_masked) >= NUM_POINT:
        idxs = np.random.choice(len(cloud_masked), NUM_POINT, replace=False)
    # 如果点数不足，先保留所有点，再随机重复补足NUM_POINT个点
    else:
        idxs1 = np.arange(len(cloud_masked))
        idxs2 = np.random.choice(len(cloud_masked), NUM_POINT - len(cloud_masked), replace=True)
        idxs = np.concatenate([idxs1, idxs2], axis=0)
    
    cloud_sampled = cloud_masked[idxs]
    color_sampled = color_masked[idxs] # 提取点云和颜色

    cloud_o3d = o3d.geometry.PointCloud()
    cloud_o3d.points = o3d.utility.Vector3dVector(cloud_masked.astype(np.float32))
    cloud_o3d.colors = o3d.utility.Vector3dVector(color_masked.astype(np.float32))

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    cloud_sampled = torch.from_numpy(cloud_sampled[np.newaxis].astype(np.float32)).to(device)
    # end_points = {'point_clouds': cloud_sampled}

    end_points = dict()
    end_points['point_clouds'] = cloud_sampled
    end_points['cloud_colors'] = color_sampled

    return end_points, cloud_o3d



# ==================== 主函数：获取抓取预测 ====================
def run_grasp_inference(color_path, depth_path, sam_mask_path=None):
    # 1. 加载网络
    net = get_net()

    # 2. 处理数据，此处使用返回的工作空间掩码路径
    end_points, cloud_o3d = get_and_process_data(color_path, depth_path, sam_mask_path)

    # 3. 前向推理
    with torch.no_grad():
        end_points = net(end_points)
        grasp_preds = pred_decode(end_points)

    # 4. 构造 GraspGroup 对象（这里 gg 是列表或类似列表的对象）
    gg = GraspGroup(grasp_preds[0].detach().cpu().numpy())

    # 5. 碰撞检测
    COLLISION_THRESH = 0.01
    if COLLISION_THRESH > 0:
        voxel_size = 0.01
        collision_thresh = 0.01
        mfcdetector = ModelFreeCollisionDetector(np.asarray(cloud_o3d.points), voxel_size=voxel_size)
        collision_mask = mfcdetector.detect(gg, approach_dist=0.05, collision_thresh=collision_thresh)
        gg = gg[~collision_mask]

    # 6. NMS 去重 + 按照得分排序（降序）
    gg.nms().sort_by_score()

    # ===== 新增筛选部分：对抓取预测的接近方向进行垂直角度限制 =====
    # 将 gg 转换为普通列表
    all_grasps = list(gg)
    world_up = np.array([0, 0, 1], dtype=np.float32)  # 世界系桌面法向
    rotation_wm = quat_wxyz_to_rotation_matrix(TABLE_OVERVIEW_QUAT)
    table_normal_cam = CV_CAMERA_TO_MUJOCO_CAMERA.T @ (rotation_wm.T @ world_up)
    angle_threshold = np.deg2rad(30)  # 30度的弧度值
    filtered = []
    for grasp in all_grasps:
        # 抓取的接近方向取 grasp.rotation_matrix 的第一列
        approach_dir = grasp.rotation_matrix[:, 0]
        # 计算夹角：cos(angle)=dot(approach_dir, vertical)
        cos_angle = np.dot(approach_dir, table_normal_cam)
        cos_angle = np.clip(cos_angle, -1.0, 1.0)
        angle = np.arccos(cos_angle)
        if angle < angle_threshold:
            filtered.append(grasp)
    if len(filtered) == 0:
        print("\n[Warning] No grasp predictions within vertical angle threshold. Using all predictions.")
        filtered = all_grasps
    else:
        print(f"\n[DEBUG] Filtered {len(filtered)} grasps within ±30° of vertical out of {len(all_grasps)} total predictions.")

    # ===== 新增部分：计算物体中心点 =====
    # 使用点云计算物体的中心点
    points = np.asarray(cloud_o3d.points)
    object_center = np.mean(points, axis=0) if len(points) > 0 else np.zeros(3)

    # 计算每个抓取位姿中心点与物体中心点的距离
    distances = []
    for grasp in filtered:
        grasp_center = grasp.translation
        distance = np.linalg.norm(grasp_center - object_center)
        distances.append(distance)

    # 创建一个新的排序列表，包含距离和抓取对象
    grasp_with_distances = [(g, d) for g, d in zip(filtered, distances)]
    
    # 按距离升序排序（距离越小越好）
    grasp_with_distances.sort(key=lambda x: x[1])
    
    # 提取排序后的抓取列表
    filtered = [g for g, d in grasp_with_distances]

    # ===== 新增部分：综合得分和距离进行最终排序 =====
    # 创建一个新的排序列表，包含综合得分和抓取对象
    # 综合得分 = 抓取得分 * 0.7 + (1 - 距离/最大距离) * 0.3
    max_distance = max(distances) if distances else 1.0
    grasp_with_composite_scores = []

    for g, d in grasp_with_distances:
        # 归一化距离分数（距离越小分数越高）
        distance_score = 1 - (d / max_distance)
        
        # 综合得分 = 抓取得分 * 权重1 + 距离得分 * 权重2
        composite_score = g.score * 0.7 + distance_score * 0.3
        # print(f"\n g.score = {g.score}, distance_score = {distance_score}")
        grasp_with_composite_scores.append((g, composite_score))

    # 按综合得分降序排序
    grasp_with_composite_scores.sort(key=lambda x: x[1], reverse=True)

    # 提取排序后的抓取列表
    filtered = [g for g, score in grasp_with_composite_scores]


    # # 对过滤后的抓取根据 score 排序（降序）
    # filtered.sort(key=lambda g: g.score, reverse=True)

    # 取第1个抓取
    top_grasps = filtered[:1]

    # 可视化过滤后的抓取，手动转换为 Open3D 物体
    grippers = [g.to_open3d_geometry() for g in top_grasps]

    # 选择得分最高的抓取（filtered 列表已按得分降序排序）
    best_grasp = top_grasps[0]
    best_translation = best_grasp.translation
    best_rotation = best_grasp.rotation_matrix
    best_width = best_grasp.width

    # 创建一个新的 GraspGroup 并添加最佳抓取
    new_gg = GraspGroup()            # 初始化空的 GraspGroup
    new_gg.add(best_grasp)           # 添加最佳抓取

    visual = True
    if visual:
        grippers = new_gg.to_open3d_geometry_list()
        o3d.visualization.draw_geometries([cloud_o3d, *grippers])

    return new_gg

    #return best_translation, best_rotation, best_width


def main():
    color_path = str(CURRENT_DIR / "output" / "table_overview.png")
    depth_path = str(CURRENT_DIR / "output" / "table_overview_depth.png")
    mask_path = str(CURRENT_DIR / "output" / "sam_result" / "masks_binary.png")

    run_grasp_inference(color_path, depth_path, mask_path)



if __name__ == "__main__":
    main()
