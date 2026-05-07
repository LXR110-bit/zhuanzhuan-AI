# mobile_use 采价指令模板（行情价专用）

## 概述
本模板用于生成稳定的mobile_use采价任务指令，确保每次都能正确获取闲鱼行情tab的"近7日成交均价"。

## 核心原则
1. **必须点进行情tab** - 搜索列表的"7日均价"不是目标价格
2. **必须截图验证** - 每个机型至少2张截图：搜索列表页 + 行情tab页
3. **不进回收估价** - 不点"回收"tab，不进"填写估价信息"
4. **每采完1个机型立即写入** - 不等全部采完

## 采价指令生成规则

### 对每个机型，指令中必须包含：
1. 明确的搜索关键词
2. "搜索后，找到顶部导航tab：全部 | AI智搜 | 个人闲置 | 严选 | 行情 | 用户，点击'行情'"
3. "行情页面会显示'近7日成交均价'和价格趋势图，读取这个均价数字"
4. 写入命令：`cd ./行情价格追踪 && python3 scripts/update_xianyu_market.py --prices '{"product_id": 价格}' --platform xianyu_market`
5. 显卡类必须加"搜完后弹出包装选项，选'无包装'"

### 机型搜索关键词与product_id对照表

| 机型 | 搜索关键词 | product_id | 特殊注意 |
|------|-----------|------------|---------|
| DJI Pocket 3 | pocket3 | dji_pocket3 | - |
| RTX 4070 | 七彩虹RTX4070 | rtx_4070 | 包装弹窗选无包装 |
| i5 13600K | i5 13600k | i5_13600k | - |
| DJI Mini 5 Pro | mini5pro | dji_mini5_pro | - |
| 金士顿DDR4 16G | 金士顿ddr4 | ddr4_16g | - |
| 小米手环10 | 小米手环10 | xiaomi_band10 | 行情tab选NFC版价格 |
| RTX 3060 | 七彩虹RTX3060 | rtx_3060 | 包装弹窗选无包装 |
| GoPro Hero12 | gopro hero12 | gopro_hero12 | - |
| DJI Air3 | 大疆air3 | dji_air3 | - |
| DJI Mini4 Pro | 大疆mini4 pro | dji_mini4_pro | - |
| DDR5 16G | 金士顿ddr5 16g | ddr5_16g | - |
| DDR4 16G（闲鱼官方回收） | 金士顿ddr4 | ddr4_16g | - |
| DJI Action5 | 大疆action5 | dji_action5 | - |
| Insta360 X4 | insta360 x4 | insta360_x4 | - |
| DJI Pocket4 | 大疆pocket4 | dji_pocket4 | - |
| RTX 3070 | 七彩虹RTX3070 | rtx_3070 | 包装弹窗选无包装 |
| i7 13700K | i7 13700k | i7_13700k | - |
| DDR5 32G | 金士顿32g内存 | ddr5_32g | 不用"金士顿ddr4 32g" |
| DJI Mini3 | dji mini3 | dji_mini3 | - |
| DJI Mini4 | dji mini4 | dji_mini4 | - |
| 小米手环9 | 小米手环9 | xiaomi_band9 | - |
| DJI Action6 | 大疆action6 | dji_action6 | - |

### 行情tab位置（截图验证点）
搜索结果页顶部导航栏：
```
全部 | AI智搜 | 个人闲置 | 严选 | 【行情】 | 用户
```
点"行情"后页面特征：
- 显示"近7日成交均价"大字价格
- 下方有价格趋势折线图
- 有"价格预判投票"区域
- 有"AI解读"区域

### 搜索列表 vs 行情tab 价格差异参考
| 机型 | 搜索列表价 | 行情tab价 | 差距 |
|------|-----------|----------|------|
| Pocket3 | ¥1533 | ¥2000 | +30% |
| RTX4070 | ¥2227 | ¥2799 | +26% |
| i5 13600K | ¥683 | ¥1240 | +82% |
| Mini5 Pro | ¥3783 | ¥4400 | +16% |
| DDR4 16G | ¥163 | ¥346 | +112% |
| 手环10 NFC | ¥115 | ¥180 | +57% |

如果取到的价格接近"搜索列表价"而非"行情tab价"，说明没有真正切到行情tab，必须重做。

## 写入验证
写入后检查：
```bash
cat ./行情价格追踪/data/price_cache.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
xm = data['prices']['{product_id}']['xianyu_market']
print(f'{product_id}: ¥{xm[\"price\"]} change={xm[\"change_1d\"]}%')
"
```

## 完整指令模板（单个机型示例）

```
采价1个机型：DJI Pocket3

操作流程（严格按步骤执行）：

1. 打开闲鱼APP
2. 在首页搜索框输入"pocket3"，点击搜索
3. 搜索结果出来后，看页面顶部导航栏：全部 | AI智搜 | 个人闲置 | 严选 | 行情 | 用户
4. 点击"行情"tab
5. 行情页面会显示"近7日成交均价"大字价格和趋势图，读取这个均价数字
6. 截图保存行情页面
7. 执行写入命令：
   cd ./行情价格追踪 && python3 scripts/update_xianyu_market.py --prices '{"dji_pocket3": 价格数字}' --platform xianyu_market
8. 验证写入：
   cat ./行情价格追踪/data/price_cache.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['prices']['dji_pocket3']['xianyu_market']['price'])"

⚠️ 关键注意：
- 必须点"行情"tab！搜索列表里的"7日均价"不是目标价格
- 不要进回收估价页面
- 不要点任何商品
- Pocket3行情tab价格约¥2000左右，如果取到¥1500左右说明没切到行情tab
```
