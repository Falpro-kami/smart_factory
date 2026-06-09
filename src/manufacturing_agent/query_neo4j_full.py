#!/usr/bin/env python3
"""
Neo4j 数据库查询脚本
查询所有节点、关系，以及特定关键词的节点
"""

from neo4j import GraphDatabase

# Neo4j 连接配置
URI = "bolt://127.0.0.1:7687"
AUTH = ("neo4j", "gc114510.")
DATABASE = "neo4j"


def query_all_nodes_and_relationships():
    """查询所有节点和关系"""
    driver = GraphDatabase.driver(URI, auth=AUTH)
    
    try:
        with driver.session(database=DATABASE) as session:
            # 1. 查询所有节点标签
            print("=" * 60)
            print("1. 所有节点标签")
            print("=" * 60)
            labels_query = "CALL db.labels() YIELD label RETURN collect(label) AS labels"
            result = session.run(labels_query)
            labels = result.single()
            print(labels["labels"] if labels else "无标签")
            
            # 2. 查询各标签节点数量
            print("\n" + "=" * 60)
            print("2. 各标签节点数量统计")
            print("=" * 60)
            count_query = """
            MATCH (n)
            RETURN labels(n) AS label, count(*) AS count
            ORDER BY count DESC
            """
            result = session.run(count_query)
            for record in result:
                label = record["label"]
                count = record["count"]
                print(f"  {label}: {count} 个节点")
            
            # 3. 查询所有关系类型
            print("\n" + "=" * 60)
            print("3. 所有关系类型")
            print("=" * 60)
            rel_query = "CALL db.relationshipTypes() YIELD relationshipType RETURN collect(relationshipType) AS types"
            result = session.run(rel_query)
            rel_types = result.single()
            print(rel_types["types"] if rel_types else "无关系")
            
            # 4. 查询部分节点示例
            print("\n" + "=" * 60)
            print("4. 节点示例 (每个标签取2个)")
            print("=" * 60)
            sample_query = """
            MATCH (n)
            WITH labels(n)[0] AS label, collect(n) AS nodes
            RETURN label, nodes[0..2] AS samples
            LIMIT 15
            """
            result = session.run(sample_query)
            for record in result:
                label = record["label"]
                samples = record["samples"]
                print(f"\n【标签: {label}】")
                for i, node in enumerate(samples):
                    props = dict(node)
                    # 隐藏长文本属性
                    for k, v in list(props.items()):
                        if isinstance(v, str) and len(v) > 50:
                            props[k] = v[:50] + "..."
                    print(f"  节点{i+1}: {props}")
            
            # 5. 统计关系数量
            print("\n" + "=" * 60)
            print("5. 各关系类型数量统计")
            print("=" * 60)
            rel_count_query = """
            MATCH ()-[r]->()
            RETURN type(r) AS rel_type, count(*) AS count
            ORDER BY count DESC
            """
            result = session.run(rel_count_query)
            for record in result:
                rel_type = record["rel_type"]
                count = record["count"]
                print(f"  {rel_type}: {count} 条")
                
    finally:
        driver.close()


def query_dog_keyword():
    """查询包含"小狗"或"dog"关键词的节点"""
    driver = GraphDatabase.driver(URI, auth=AUTH)
    
    try:
        with driver.session(database=DATABASE) as session:
            print("\n" + "=" * 60)
            print("查询包含'小狗'或'dog'关键词的节点")
            print("=" * 60)
            
            # 查询包含"小狗"或"dog"的节点
            dog_query = """
            MATCH (n)
            WHERE any(prop IN keys(n) WHERE 
                toLower(n[prop]) CONTAINS '小狗' OR 
                toLower(n[prop]) CONTAINS 'dog')
            RETURN labels(n) AS label, n.name AS name, n.title AS title, properties(n) AS props
            LIMIT 50
            """
            result = session.run(dog_query)
            count = 0
            for record in result:
                count += 1
                label = record["label"]
                name = record.get("name", "N/A")
                title = record.get("title", "N/A")
                props = record["props"]
                print(f"\n节点 {count}:")
                print(f"  标签: {label}")
                print(f"  name: {name}")
                print(f"  title: {title}")
                print(f"  属性: {props}")
            
            if count == 0:
                print("未找到包含'小狗'或'dog'的节点")
                
    finally:
        driver.close()


def query_installation_process():
    """查询标签为"安装流程"或类似的节点"""
    driver = GraphDatabase.driver(URI, auth=AUTH)
    
    try:
        with driver.session(database=DATABASE) as session:
            print("\n" + "=" * 60)
            print("查询标签为'安装流程'或类似的节点")
            print("=" * 60)
            
            # 查询安装流程相关标签
            install_query = """
            MATCH (n)
            WHERE any(label IN labels(n) WHERE 
                label CONTAINS '安装' OR 
                label CONTAINS '流程' OR
                label CONTAINS 'Install' OR
                label CONTAINS 'Process')
            RETURN labels(n) AS label, n.name AS name, properties(n) AS props
            LIMIT 30
            """
            result = session.run(install_query)
            count = 0
            for record in result:
                count += 1
                label = record["label"]
                name = record.get("name", "N/A")
                props = record["props"]
                print(f"\n节点 {count}:")
                print(f"  标签: {label}")
                print(f"  name: {name}")
                print(f"  属性: {props}")
            
            if count == 0:
                # 如果没有找到，列出所有标签供查看
                print("\n未找到安装流程相关标签，以下是所有标签:")
                labels_query = "CALL db.labels() YIELD label RETURN collect(label) AS labels"
                result = session.run(labels_query)
                labels = result.single()
                print(labels["labels"])
                
    finally:
        driver.close()


def query_dog_kg_structure():
    """查询小狗相关的知识图谱结构"""
    driver = GraphDatabase.driver(URI, auth=AUTH)
    
    try:
        with driver.session(database=DATABASE) as session:
            print("\n" + "=" * 60)
            print("小狗相关的知识图谱结构")
            print("=" * 60)
            
            # 查找与小狗相关的节点
            dog_kg_query = """
            MATCH (n)-[r]->(m)
            WHERE any(prop IN keys(n) WHERE 
                toLower(n[prop]) CONTAINS '小狗' OR 
                toLower(n[prop]) CONTAINS 'dog')
            RETURN n.name AS source, type(r) AS rel, m.name AS target
            LIMIT 30
            """
            result = session.run(dog_kg_query)
            print("\n从小狗节点出发的关系:")
            count = 0
            for record in result:
                count += 1
                source = record["source"]
                rel = record["rel"]
                target = record["target"]
                print(f"  {source} --[{rel}]--> {target}")
            
            if count == 0:
                print("  未找到从小狗节点出发的关系")
                
            # 查找以小狗节点为目标的路径
            dog_kg_query2 = """
            MATCH (n)-[r]->(m)
            WHERE any(prop IN keys(m) WHERE 
                toLower(m[prop]) CONTAINS '小狗' OR 
                toLower(m[prop]) CONTAINS 'dog')
            RETURN n.name AS source, type(r) AS rel, m.name AS target
            LIMIT 30
            """
            result = session.run(dog_kg_query2)
            print("\n指向小狗节点的关系:")
            count = 0
            for record in result:
                count += 1
                source = record["source"]
                rel = record["rel"]
                target = record["target"]
                print(f"  {source} --[{rel}]--> {target}")
            
            if count == 0:
                print("  未找到指向小狗节点的关系")
                
    finally:
        driver.close()


if __name__ == "__main__":
    print("开始查询 Neo4j 数据库...")
    print()
    
    # 1. 查询所有节点和关系
    query_all_nodes_and_relationships()
    
    # 2. 查询包含小狗/dog关键词的节点
    query_dog_keyword()
    
    # 3. 查询标签为安装流程的节点
    query_installation_process()
    
    # 4. 查询小狗相关知识图谱结构
    query_dog_kg_structure()
    
    print("\n" + "=" * 60)
    print("查询完成!")
    print("=" * 60)