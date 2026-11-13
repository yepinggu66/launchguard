# 收款说明（用你的 PayPal）

现在的代码已经能收钱了，但**用 paypal.me 收 B2B 的 $29 是最差的一档**。下面按"今天能收"到"一个月后该长成什么样"排。

## 1. 现在已经跑通的（今天就能收）

- 定价页按钮 → `https://www.paypal.me/pinggu80/29USD`（已验证会显示 `$29.00 USD` + Send）
- 买家付款后填表（仓库 + 邮箱 + 交易号）→ 写进数据库 → 你手动交付
- 站点：`https://launchguard-production-e3a01252.up.railway.app/pricing`

这条路径的问题很具体，不是"不够优雅"：

| 问题 | 后果 |
|---|---|
| paypal.me 是**个人对个人转账** | 没有商品名、没有买家保护、没有发票，欧美工程师看到"给一个陌生人转 $29"会直接关掉 |
| 个人账户 + 中文昵称 | 目标客群不信任，转化率打折 |
| 无法订阅 | 你只能卖一次性服务，收不到 MRR |
| 手动交付 | 每单要你在线；睡觉时进的钱要第二天才处理 |

## 2. 五分钟升级（强烈建议今天做）

把个人账户升级成 **PayPal 商业账户**（免费，不用公司），然后建一个 **Payment Link**：

1. PayPal 后台 → **Tools / 收款工具** → **Payment Links**（或 "Create a payment link"）
2. 商品名：`Launch Guard audit — 1 repo`，价格 `29.00 USD`
3. 打开 "Collect customer info"（收邮箱）和 "Add a note"（让买家填仓库地址）
4. 付款成功后跳转设为：`https://launchguard-production-e3a01252.up.railway.app/thanks`
5. 复制生成的 `https://www.paypal.com/ncp/payment/XXXXXXXX`
6. 在 Railway 里加环境变量并重启：

```
PAYPAL_LINK=https://www.paypal.com/ncp/payment/XXXXXXXX
```

代码已经支持这个变量（有它就不再用 paypal.me），无需改代码、无需重新部署，改环境变量即可。

升级后的差别：正规收银台、显示商品名和你的店铺名、买家有 PayPal 买家保护、能开发票、能退款、能收信用卡（不必注册 PayPal）。

## 3. 想要"每月自动扣"（MRR）

$29 一次性适合前 10 单，不适合做产品。两条路：

| 方案 | 适合 | 代价 |
|---|---|---|
| **PayPal Subscriptions** | 已有商业账户、只面向 PayPal 用户 | 要在后台建 product/plan，前端要接 JS SDK；不支持支付宝/微信；税仍要你自己处理 |
| **Paddle / Lemon Squeezy / Creem** | 面向全球、想省税务 | 审核 1–3 天；抽成约 5% + 支付费；但它们是 MoR，VAT/销售税由它们代缴 |

如果目标是"欧美独立开发者 + 每月 $19"，**Paddle 或 Lemon Squeezy 比 PayPal 订阅更省事**：你不需要注册美国公司，也不需要处理欧盟 VAT。

## 4. 费用与税务（按你现在的情况）

- 你是香港账户：香港没有 VAT/销售税，你不需要代收。
- 但欧盟/英国买家可能需要 VAT 发票，美国部分州对 SaaS 征税 —— 这些只有 MoR（Paddle/LS）能替你处理。$29 一单的量级，先不用管，但别对买家承诺"含税发票"。
- PayPal 商业收款费率大约 3.49% + 固定费，跨境再加约 1–1.5%：$29 到手约 $27.4–27.7。可以接受。

## 5. 定价建议（按现在的产品力）

| 档 | 价格 | 内容 | 目的 |
|---|---|---|---|
| 免费 | $0 | 公开仓库扫描 + GitHub Action + README 徽章 | 唯一的分发渠道 |
| **Audit** | **$29 一次性** | 1 个仓库，人工确认每条发现，回一个修复 PR | 首单、验证付费意愿 |
| Team | $99 一次性 | 最多 5 个仓库 + 生成 `policy.yaml` | 提高客单价 |
| Pro（以后） | $19/月 | 私有仓库持续扫描 + PR 里自动修复建议 | MRR，但要先有 20 个免费用户在跑 |

## 6. 交付 SOP（每单 20 分钟）

1. 收到订单（数据库 `orders` 表 / 邮件）
2. `python -m guard.cli scan <repo>` 出报告
3. **逐条打开 `file:line` 确认**，删掉误报（这是 $29 买的东西）
4. 写 3 条以内的"真正要改的"，附上 `fix_prompt`
5. 发邮件 + 附 fix PR 链接
6. 问一句："要不要我把它接进你们的 CI"

第 3 步不能省。没有人工确认，$29 就只是在卖一个本来就免费的扫描器。

## 7. 运行手册（部署后）

**看订单**（手机也能开，建议存书签）：

```
https://launchguard-production-e3a01252.up.railway.app/admin/orders?key=<ADMIN_KEY>
```

`ADMIN_KEY` 在 Railway 变量里，也在本机 `launchguard/.admin-key.txt`。这个页面把每单标成
`paid / delivered / refunded`，是唯一需要你每天看一次的地方。没有 key 直接 404（不是 401，
不告诉扫描器这里有什么）。

**新订单通知**：设一个 `ORDER_WEBHOOK_URL`，每来一单就往那里 POST 一段 JSON
（`order_id / repo / email / txn / created_at`）。最省事的两个来源：

- Discord：频道 → 设置 → 集成 → Webhook → 复制 URL（2 分钟，不用建应用）
- Telegram：@BotFather 建 bot 拿 token，再调 `getUpdates` 拿 chat_id

拿到 URL 后：

```powershell
railway variables --set "ORDER_WEBHOOK_URL=<url>" --skip-deploys
railway up -d -y
```

**数据在哪**：`/data/launchguard.db`（Railway volume）。备份：

```powershell
railway volume files /data/launchguard.db
```

**轮换 admin key**：重新生成一个随机串，`railway variables --set ADMIN_KEY=...`，重启即生效。

**法律页**：`/terms` 和 `/privacy` 已经上线（退款承诺写在里面：48 小时未交付全额退）。联系人默认是
`yepinggu@outlook.com`，用 `CONTACT_EMAIL` 变量可改。

**分享报告页是 noindex 的**——不要把客户仓库的问题送进搜索引擎，这是有意的。
