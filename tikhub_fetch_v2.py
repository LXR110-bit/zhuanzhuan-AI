import json
import requests
from datetime import datetime, timedelta

API_KEY = "oYMGXtwo9W+7qmeZQ7WwnSeAZzqWZ5Zt4yP5o2iMcuK2ugrmHn6CWy+RaA=="
BILIBILI_ENDPOINT = "https://api.tikhub.dev/api/v1/bilibili/app/fetch_search_all"

SEARCH_KEYWORDS = [
    {"keyword": "RTX4070 二手价格", "category": "显卡"},
    {"keyword": "Pocket3 二手回收", "category": "运动相机"}
]

def fetch_bilibili(keyword):
    headers = {"Authorization": f"Bearer {API_KEY}"}
    params = {"keyword": keyword, "page": 1}
    try:
        resp = requests.get(BILIBILI_ENDPOINT, headers=headers, params=params, timeout=60)
        if resp.status_code == 200:
            return resp.json()
        else:
            return {"error": f"HTTP {resp.status_code}", "detail": resp.text[:200]}
    except Exception as e:
        return {"error": str(e)}

def filter_recent(days=7):
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

def main():
    results = {
        "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "platform": "bilibili",
        "date": "2026-05-05",
        "weekday": "周二",
        "data": []
    }
    
    recent_date = filter_recent()
    print(f"筛选7天内内容（{recent_date}之后）...")
    
    for item in SEARCH_KEYWORDS:
        print(f"\n搜索 [{item['category']}]: {item['keyword']}")
        kw = item['keyword']
        data = fetch_bilibili(kw)
        
        if "error" in data:
            print(f"  ❌ 失败: {data}")
            results["data"].append({
                "category": item["category"],
                "keyword": item["keyword"],
                "status": "failed",
                "error": data["error"]
            })
            continue
        
        items = data.get("data", {}).get("items", [])
        print(f"  获取到 {len(items)} 条原始结果")
        
        filtered = []
        for i in items:
            pub_date = i.get("pubdate", "")
            if pub_date and pub_date >= recent_date:
                filtered.append(i)
        
        filtered.sort(key=lambda x: x.get("like", 0) + x.get("coin", 0)*2 + x.get("favorite", 0)*2, reverse=True)
        top3 = filtered[:3]
        
        print(f"  7天内: {len(filtered)} 条，Top3已筛选")
        
        results["data"].append({
            "category": item["category"],
            "keyword": item["keyword"],
            "status": "success",
            "total_recent": len(filtered),
            "top3": [{
                "title": i.get("title", ""),
                "author": i.get("author", ""),
                "pubdate": i.get("pubdate", ""),
                "like": i.get("like", 0),
                "coin": i.get("coin", 0),
                "favorite": i.get("favorite", 0),
                "desc": (i.get("desc") or "")[:200],
                "short_link": i.get("short_link", "")
            } for i in top3]
        })
    
    return results

if __name__ == "__main__":
    result = main()
    
    output_path = "./行情价格追踪/data/tikhub_signals.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n已保存到 {output_path}")
