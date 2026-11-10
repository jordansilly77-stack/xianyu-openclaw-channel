# 离线客服恢复说明

这次在当前 fork 上加了一条可离线运行的待审客服。它不是旧本机目录 `~/.openclaw/workspace/tmp/xianyu-openclaw-channel/` 的找回，仓库里也没有 `safari_token.py` 或 launchd 配置。

## 本地安全验收

在仓库根目录执行：

```bash
python -m kefu_offline
python -m kefu_offline --generator mock
python -m pytest tests/test_kefu_offline.py tests/test_item_binding_facts.py -q
```

这三条都不会启动 `Start.py`，不会跑 `install-openclaw.sh` / `install-openclaw.bat`，不会打开 WebSocket，也不会发送消息。`mock` 只表示规则引擎丢掉了一份故意违规的假草稿，不是模型调用，不能称为端到端 AI 实测。

通过时，规则回放和 mock 回放的 `failed` 都是 0，每条 `send_allowed` 和 `model_invoked` 都是 false。

## 已证实

对照的是本仓库当前 `main` 上的代码，加上本次离线测试。

- `Start.py` 默认端口是 8080。`global_config.yml` 里 `AUTO_REPLY.enabled` 为 true，默认回复文案含有「可以直接申请退款」。本次没有启动这条线上路径。
- 商品 ID 有两条不一样的读法。`handle_message` 在 `message["1"]` 是字典时，会先读 `reminderUrl` 的 `itemId`。其后的 `extract_item_id_from_message` 会递归抓任意 10 位以上数字。用仓库里的原函数跑一条同时带卖家可见字段和买家数字的示例消息时，这个后备函数返回的是 `senderUserId`（`2207836320265`），不是 URL 里的 `100200300400`。
- URL 缺失时，`handle_message` 会把商品 ID 写成 `auto_{user_id}_{timestamp}`。库里没有这条商品时，`get_ai_reply` 仍用标题「商品信息获取失败」、价格 0 继续调用 `generate_reply`。
- `message["1"]` 为列表时，`is_chat_message` 会把它当成聊天消息，但 `handle_message` 随后要求 `message["1"]` 必须是字典，并在发布到 Bridge 之前返回。后备提取函数本身不遍历列表，原函数对这种包裹返回 `None`。
- Bridge 发布前会用 `item_info` 做归属过滤。本地没有这条商品时，消息不会进队列。`openclaw-plugin/src/types.ts` 有可选的 `itemId`，Python 发布体也会带上它；`inbound-handler.ts` 没有读取 `itemId`，交给 Agent 的正文只用 `data.content`。
- 现有技能只有 `openclaw-plugin/skills/xianyu-product`，内容是发布商品。没有客服技能。长提示词没有被这次恢复当成有效约束。
- 上游 `laozuzhen/xianyu-openclaw-channel` 的 issue #4（已关闭）和 #5（仍开放）标题都是闲鱼回复不能感知当前咨询的商品，#5 还写了要在 skill 里限定回复、多商品不好管理。#5 正文是一张截图，本次没有把截图当作根因。上面几条是代码事实，能分别造成「对不上商品」或「Agent 看不到商品」，但不能从标题单独断定作者当时碰到的是哪一种。
- 新的 `kefu_offline` 只用可信字段里的商品 ID。买家正文里的商品名、`itemId=` 或别的数字不能选商品，也不能把已绑定的对话改到另一件商品。对不上商品、范围、价格、工期、型号、成色、退款时，草稿是转人工，不补事实。
- 示例目录里的服务类没有标价。旧标价 20 元只写在目录说明里，不会进入买家可见草稿。路由器示例只在买家询问标价、且没有还价或别的未确认问题时复述「标价310元，包邮。」还价、型号、成色不会带出 310，也不会编底价。
- 回放默认不发送。`deliver()` 收到 transport 也不会调用它。

## 未验证

- 没有连接闲鱼，没有读私信，没有用真实会话回放。
- 没有调用任何模型。`--generator mock` 不是 AI 实测。
- 没有运行 `Start.py`、安装脚本、OpenClaw Gateway 或浏览器。
- 没有打开 issue #5 的截图，也没有复现作者界面上的那一次失败。
- 示例商品不是店里的在售链接。310 元包邮和「旧标价 20 元不能套用」只来自这次任务里的用户陈述。

## 旧定制不可恢复

指定的旧路径和备份没有提供副本。本仓库没有 `safari_token.py`，也没有 `com.openclaw.xianyu-bridge.plist`。不能把上游或这份 fork 说成那套本机定制。

## 缺失配置

这些资料不在仓库里，本次也不收集 Cookie、token 或账号。

- 真实商品 ID，以及每条链接对应的是哪一项服务或路由器。
- 服务范围、工期、可公开的成交价、底价。20 元不能填进这些空位。
- 路由器型号、成色、底价。
- 模型供应商、模型名、API key。没有这些就不能做真实模型回复。
- OpenClaw 的本机 `accountId`、Bridge token、Cookie。验收不需要它们。

## 已知缺口

- 线上自动回复仍按 `global_config.yml` 打开。按 README 启动 `Start.py` 且账号可用时，旧代码仍会走关键词、AI 和默认回复，并可能直接发送。离线引擎没有接进这条路径。
- 插件仍不把 `itemId` 放进 Agent 上下文。这次没有改插件，避免在仍会自动发送的链路上只补一段提示。
- 审核通过后的发送没有实现，也没有开关可以把 `send_allowed` 改成 true。
- 关键词回复和 AI 议价提示仍在旧文件里，离线回放不调用它们。

## 最小后续路线

1. 继续用上面的三条命令验收，不要为了验收去安装或启动线上服务。
2. 若要替换示例目录，只补真实、可公开、并且能标明来源的商品资料。型号、成色、范围、工期、底价仍未知时保持空，让回复转人工。
3. 保持待审和禁止发送。不要用技能提示词代替代码里的商品绑定和承诺检查。
4. 只有在发送默认关闭、并且可信商品 ID 能进入待审记录之后，才讨论是否把同一套检查接到现有 Bridge。那一步不在本次范围内。
