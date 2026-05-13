#!/usr/bin/env python3
"""
阈值自适应模块 - 云电脑价格追踪系统
功能：根据验证结果自动调整置信度阈值
验证成功→阈值提高（减少误报），验证失败→阈值降低（减少漏报）
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List


class ThresholdAdapter:
    """阈值自适应调整器"""
    
    def __init__(self, base_path: str = "."):
        self.base_path = Path(base_path)
        self.data_dir = self.base_path / "data"
        self.config_file = self.data_dir / "threshold_config.json"
        
        # 默认阈值
        self.default_thresholds = {
            "zscore": 2.0,
            "iqr_factor": 1.5,
            "pct_change": 0.15,
            "gradient": 0.1,
            "percentile_low": 5,
            "percentile_high": 95
        }
        
        # 调整参数
        self.params = {
            "increase_step": 0.1,
            "decrease_step": 0.1,
            "min": 1.0,
            "max": 3.0,
            "cooldown_hours": 24
        }
        
        self.thresholds = self.load_config()
        self.validation_history: List[Dict] = self.load_history()
        self.last_adjustment = self._get_last_adjustment()
    
    def load_config(self) -> Dict:
        """加载阈值配置"""
        if self.config_file.exists():
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f).get("thresholds", self.default_thresholds)
        return self.default_thresholds.copy()
    
    def save_config(self):
        """保存阈值配置"""
        config = {
            "thresholds": self.thresholds,
            "last_updated": datetime.now().isoformat()
        }
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        print(f"[阈值更新] {self.thresholds}")
    
    def load_history(self) -> List[Dict]:
        """加载验证历史"""
        hist_file = self.data_dir / "validation_history.json"
        if hist_file.exists():
            with open(hist_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []
    
    def save_history(self):
        """保存验证历史"""
        hist_file = self.data_dir / "validation_history.json"
        with open(hist_file, 'w', encoding='utf-8') as f:
            json.dump(self.validation_history[-100:], f, ensure_ascii=False, indent=2)
    
    def _get_last_adjustment(self) -> str:
        """获取上次调整时间"""
        adj_file = self.data_dir / "adjustment_history.json"
        if adj_file.exists():
            with open(adj_file, 'r', encoding='utf-8') as f:
                return json.load(f).get("last_adjustment")
        return None
    
    def can_adjust(self) -> bool:
        """检查冷却期"""
        if not self.last_adjustment:
            return True
        elapsed = datetime.now() - datetime.fromisoformat(self.last_adjustment)
        return elapsed >= timedelta(hours=self.params["cooldown_hours"])
    
    def record_validation(self, product: str, success: bool):
        """
        记录验证结果
        success=True: 预测正确 → 提高阈值（减少误报）
        success=False: 预测错误 → 降低阈值（减少漏报）
        """
        self.validation_history.append({
            "timestamp": datetime.now().isoformat(),
            "product": product,
            "success": success,
            "action": "increase" if success else "decrease"
        })
        self.save_history()
        
        # 自动检查是否需要调整
        if len(self.validation_history) >= 3:
            self._auto_adjust()
    
    def _auto_adjust(self):
        """根据验证历史自动调整"""
        if not self.can_adjust():
            return
        
        # 统计近48小时验证
        cutoff = datetime.now() - timedelta(hours=48)
        recent = [v for v in self.validation_history 
                  if datetime.fromisoformat(v["timestamp"]) >= cutoff]
        
        if len(recent) < 3:
            return
        
        success_rate = sum(1 for v in recent if v["success"]) / len(recent)
        print(f"[阈值检查] 近48h验证: {sum(1 for v in recent if v['success'])}/{len(recent)} 成功 ({success_rate:.0%})")
        
        if success_rate >= 0.9:
            self._adjust("increase")
        elif success_rate < 0.6:
            self._adjust("decrease")
    
    def _adjust(self, direction: str):
        """执行阈值调整"""
        print(f"[阈值调整] {direction}")
        
        for key in ["zscore", "iqr_factor", "pct_change", "gradient"]:
            if key not in self.thresholds:
                continue
            
            current = self.thresholds[key]
            step = self.params["increase_step"] if direction == "increase" else self.params["decrease_step"]
            
            if direction == "increase":
                new_val = min(current + step, self.params["max"])
            else:
                new_val = max(current - step, self.params["min"])
            
            self.thresholds[key] = round(new_val, 2)
        
        self.save_config()
        
        # 保存调整历史
        with open(self.data_dir / "adjustment_history.json", 'w', encoding='utf-8') as f:
            json.dump({
                "last_adjustment": datetime.now().isoformat(),
                "direction": direction,
                "thresholds": self.thresholds
            }, f, ensure_ascii=False, indent=2)
    
    def manual_set(self, **kwargs):
        """手动设置阈值"""
        self.thresholds.update(kwargs)
        self.save_config()
    
    def reset(self):
        """重置为默认值"""
        self.thresholds = self.default_thresholds.copy()
        self.save_config()
    
    def get_thresholds(self) -> Dict:
        """获取当前阈值"""
        return self.thresholds.copy()
    
    def get_stats(self) -> Dict:
        """获取验证统计"""
        if not self.validation_history:
            return {"total": 0, "success": 0, "success_rate": 0}
        
        total = len(self.validation_history)
        success = sum(1 for v in self.validation_history if v["success"])
        return {
            "total": total,
            "success": success,
            "fail": total - success,
            "success_rate": round(success / total * 100, 1)
        }


def main():
    """CLI交互"""
    import sys
    
    adapter = ThresholdAdapter(base_path=".")
    
    if len(sys.argv) < 2:
        print("=" * 50)
        print("阈值自适应模块")
        print("=" * 50)
        print(f"当前阈值: {adapter.get_thresholds()}")
        print(f"验证统计: {adapter.get_stats()}")
        print("\n用法:")
        print("  python threshold.py status")
        print("  python threshold.py record <product> <success|fail>")
        print("  python threshold.py set zscore=2.5")
        print("  python threshold.py reset")
        return
    
    cmd = sys.argv[1]
    
    if cmd == "status":
        print(f"阈值: {adapter.get_thresholds()}")
        print(f"统计: {adapter.get_stats()}")
    
    elif cmd == "record" and len(sys.argv) >= 4:
        product = sys.argv[2]
        success = sys.argv[3].lower() in ("success", "true", "1", "yes")
        adapter.record_validation(product, success)
    
    elif cmd == "set" and len(sys.argv) >= 3:
        updates = {}
        for arg in sys.argv[2:]:
            if "=" in arg:
                k, v = arg.split("=", 1)
                try:
                    updates[k] = float(v)
                except ValueError:
                    updates[k] = v
        adapter.manual_set(**updates)
    
    elif cmd == "reset":
        adapter.reset()


if __name__ == "__main__":
    main()
