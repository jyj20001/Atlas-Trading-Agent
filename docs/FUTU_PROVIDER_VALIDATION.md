# FutuProvider Validation Report

**日期:** 2026-07-26
**版本:** v1.0
**模块:** `data/kline_providers/futu_provider.py`

---

## 状态: ✅ 代码就绪，等待 OpenD 启动

FutuProvider 已开发完成并通过单元测试。
**OpenD 当前未运行**，无法进行实际数据获取测试。

---

## 已验证

| 测试 | 断言 | 结果 |
|------|:----:|:----:|
| FutuProvider 导入 + 基本属性 | 3 | ✅ |
| A股代码转富途格式 (SH/SZ/BJ) | 6 | ✅ |
| Provider 链条件导入 | 3 | ✅ |
| 复权类型 AuType (QFQ/HFQ/NONE) | 3 | ✅ |
| 分页逻辑代码结构 | 3 | ✅ |
| **合计** | **18** | **✅ 5/5** |

---

## 架构

```
Provider 链优先级:
  1. FutuProvider (priority=-1)  ← 最高，条件导入
  2. EastMoneyProvider (priority=0)
  3. TencentProvider (priority=1)  ← fallback
```

**条件导入:** 仅当 `futu-api` Python SDK 已安装时，FutuProvider 才加入链。

---

## 使用说明

### 启动 OpenD

```bash
# 1. 从富途开发者平台下载 OpenD
#    https://openapi.futunn.com/v2/guide.html

# 2. 启动 OpenD（默认端口 11111）
./FutuOpenD

# 3. 验证连接
python3 -c "
from futu import OpenQuoteContext
ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
print('OpenD connected')
"
```

### 已知问题

| 问题 | 说明 |
|------|------|
| OpenD 需要独立下载 | 不在 futu-api SDK 内 |
| 需要富途开发者账号 | 免费注册 |
| 需要牛牛客户端登录 | 已有 |
| 首次连接可能需要行情权限 | A 股行情通常免费 |

### 未来集成计划

OpenD 连接到 Provider 链后，`fetch_klines()` 将自动优先使用 FutuProvider：

```
Futu (全量历史) → EastMoney (失败快) → Tencent (640根)
```

---

*代码已就绪。待 OpenD 启动后可立即激活完整历史回测。*
