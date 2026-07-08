# 🔑 API 密钥获取指南

> ⚠️ **不要在此文件中填写真实密钥！** 所有密钥应配置在 `.env` 文件中（复制 `.env.example` 为 `.env`）。

## 数据源

| 提供商 | 环境变量 | 免费? | 注册地址 | 用途 |
|--------|---------|-------|---------|------|
| **mootdx** | 无需配置 | ✅ 免费 | 无需注册 | 通达信标准行情（默认） |
| **腾讯行情** | 无需配置 | ✅ 免费 | 无需注册 | 腾讯 K 线数据 |
| **AKShare** | 无需配置 | ✅ 免费 | 无需注册 | 爬虫聚合数据 |
| **妙想金融** | `MX_APIKEY` | ❌ 需申请 | https://miaoxiang.dfcfs.com | AI 金融数据 |
| **国信证券** | `GS_API_KEY` | ❌ 需申请 | 联系国信证券 | 券商 API |
| **华泰证券** | `HT_APIKEY` | ❌ 需申请 | 联系华泰证券 | 市场洞察 |

## AI 模型

| 提供商 | 环境变量 | 免费? | 注册地址 |
|--------|---------|-------|---------|
| **Anthropic** | `ANTHROPIC_API_KEY` | ❌ | https://console.anthropic.com |
| **OpenAI** | `OPENAI_API_KEY` | ❌ | https://platform.openai.com |
| **DeepSeek** | `DEEPSEEK_API_KEY` | ❌ | https://platform.deepseek.com |

## 最小配置

**零成本即可使用**：mootdx + 腾讯 + AKShare 均免费，无需任何 API 密钥。

```bash
cp .env.example .env
# 编辑 .env，至少填写一个 AI 模型密钥（用于诊断分析）
# 数据源密钥可选，不填则自动使用免费数据源
```

## 数据源优先级

```
华泰(HT_APIKEY) > 国信(GS_API_KEY) > 腾讯(免费) > mootdx(TCP) > AKShare
```

系统会自动降级：配了付费源就用付费源，没配就用免费源。不会因为缺密钥而崩溃。
