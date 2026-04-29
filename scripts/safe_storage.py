#!/usr/bin/env python3
"""
并发安全存储模块
功能：原子写入、文件锁、数据去重合并
"""
import json
import os
import fcntl
from pathlib import Path
from datetime import datetime

class SafeJsonStorage:
    def __init__(self, base_dir: str = None):
        if base_dir is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            base_dir = os.path.join(os.path.dirname(script_dir), "data")
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(exist_ok=True)
    
    def _get_path(self, subdir: str, filename: str) -> Path:
        path = self.base_dir / subdir
        path.mkdir(parents=True, exist_ok=True)
        return path / filename
    
    def save_json(self, data: dict, subdir: str, filename: str) -> bool:
        """原子写入JSON文件"""
        file_path = self._get_path(subdir, filename)
        tmp_path = file_path.with_suffix('.tmp')
        
        try:
            # 写入临时文件
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # 原子替换
            os.replace(tmp_path, file_path)
            return True
        except Exception as e:
            print(f"[SafeStorage] 写入失败: {e}")
            if tmp_path.exists():
                tmp_path.unlink()
            return False
    
    def load_json(self, subdir: str, filename: str) -> dict:
        """读取JSON文件"""
        file_path = self._get_path(subdir, filename)
        if not file_path.exists():
            return {}
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[SafeStorage] 读取失败: {e}")
            return {}
    
    def append_to_cache(self, data: dict, subdir: str, filename: str, merge_key: str = None) -> bool:
        """
        追加数据到缓存文件（支持去重合并）
        merge_key: 用于去重的字段名，如 'product_id'
        """
        file_path = self._get_path(subdir, filename)
        lock_path = file_path.with_suffix('.lock')
        
        try:
            # 文件锁
            with open(lock_path, 'w') as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                
                try:
                    # 读取现有数据
                    existing = {}
                    if file_path.exists():
                        with open(file_path, 'r', encoding='utf-8') as f:
                            existing = json.load(f)
                    
                    # 合并数据
                    if merge_key and merge_key in data:
                        existing[merge_key] = data
                    else:
                        existing.update(data)
                    
                    # 更新时间戳
                    existing['last_updated'] = datetime.now().isoformat()
                    
                    # 原子写入
                    tmp_path = file_path.with_suffix('.tmp')
                    with open(tmp_path, 'w', encoding='utf-8') as f:
                        json.dump(existing, f, ensure_ascii=False, indent=2)
                    os.replace(tmp_path, file_path)
                    
                    return True
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        except Exception as e:
            print(f"[SafeStorage] 追加失败: {e}")
            return False
        finally:
            # 清理锁文件
            if lock_path.exists():
                try:
                    lock_path.unlink()
                except:
                    pass
    
    def write_with_timestamp(self, data: dict, subdir: str, prefix: str = "") -> Path:
        """带时间戳的文件写入（用于归档）"""
        timestamp = datetime.now().strftime("%Y-%m-%d")
        filename = f"{prefix}_{timestamp}.json" if prefix else f"{timestamp}.json"
        self.save_json(data, subdir, filename)
        return self._get_path(subdir, filename)


if __name__ == "__main__":
    # 测试
    storage = SafeJsonStorage()
    
    # 测试写入
    test_data = {"test": "hello", "time": datetime.now().isoformat()}
    storage.save_json(test_data, "test", "test.json")
    
    # 测试读取
    loaded = storage.load_json("test", "test.json")
    print(f"读取结果: {loaded}")
