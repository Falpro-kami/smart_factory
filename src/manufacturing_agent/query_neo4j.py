from neo4j import GraphDatabase

# Neo4j 连接配置
URI = "bolt://127.0.0.1:7687"
AUTH = ("neo4j", "gc114510.")
DATABASE = "neo4j"

def query_nodes():
    driver = GraphDatabase.driver(URI, auth=AUTH)
    
    try:
        with driver.session(database=DATABASE) as session:
            # 查询所有节点标签
            labels_query = """
            CALL db.labels() YIELD label
            RETURN collect(label) AS labels
            """
            result = session.run(labels_query)
            labels = result.single()
            print("=== 节点标签 ===")
            print(labels["labels"] if labels else "无标签")
            
            # 查询节点数量统计
            print("\n=== 各标签节点数量 ===")
            count_query = """
            MATCH (n)
            RETURN labels(n) AS label, count(*) AS count
            ORDER BY count DESC
            """
            result = session.run(count_query)
            for record in result:
                print(f"{record['label']}: {record['count']}")
            
            # 查询所有关系类型
            print("\n=== 关系类型 ===")
            rel_query = """
            CALL db.relationshipTypes() YIELD relationshipType
            RETURN collect(relationshipType) AS types
            """
            result = session.run(rel_query)
            rel_types = result.single()
            print(rel_types["types"] if rel_types else "无关系")
            
            # 查询部分节点示例
            print("\n=== 节点示例 (每个标签取3个) ===")
            sample_query = """
            MATCH (n)
            WITH labels(n)[0] AS label, collect(n) AS nodes
            RETURN label, nodes[0..3] AS samples
            LIMIT 10
            """
            result = session.run(sample_query)
            for record in result:
                label = record["label"]
                samples = record["samples"]
                print(f"\n标签: {label}")
                for i, node in enumerate(samples):
                    props = dict(node)
                    # 隐藏长文本属性
                    for k, v in list(props.items()):
                        if isinstance(v, str) and len(v) > 50:
                            props[k] = v[:50] + "..."
                    print(f"  节点{i+1}: {props}")
    finally:
        driver.close()

if __name__ == "__main__":
    query_nodes()