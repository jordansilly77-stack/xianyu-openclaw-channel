# 客服待审路径

买家消息进入 `XianyuLive.handle_message` 后，用协议里的商品字段识别商品，再写成待审草稿。默认不发送。`python -m kefu_offline --mac-preview` 使用同一套识别、规则和模型函数，但消息是模拟的，不会打开闲鱼连接。

## Mac 上的单次模型预览

在用户 Mac 上执行。`127.0.0.1:3425` 只在这台 Mac 的 loopback 上，云端虚拟机没有访问它。密钥从本机已有正式配置读取，通过环境变量传入，不要写进仓库、日志或命令历史之外的文件。

```bash
cd /path/to/xianyu-openclaw-channel
export OPENAI_BASE_URL="http://127.0.0.1:3425/v1"
export OPENAI_MODEL="group/free-first"
export OPENAI_API_KEY="从本机正式配置读取"
export OPENAI_TIMEOUT="30"
python -m kefu_offline --mac-preview \
  --catalog kefu_offline/fixtures/mac_preview_catalog.yml \
  --replay kefu_offline/fixtures/mac_preview_batch.json
```

四条都是 15 元模拟商品或未知商品，不使用 20 元或 310 元。已能根据资料回答的才会调模型；工期和退款都没填、或者商品对不上时，只留下待审草稿，不再请求模型。口吻按 `kefu_offline/style.py` 和 `openclaw-plugin/skills/xianyu-kefu/SKILL.md`。在售可以答「在的」，不必复述「在售」；已售出再说在会被挡住。泛砍价只重复标价，买家明确报低价才写「不行」。问成色而没有成色等级时只说没确认，不把功能写成成色，也不编「成色一般」。没问成色时不主动报没确认。多问并进一句，AI 身份不伪装。运费按资料原句答，不靠五个城市的名单。已知事实能答就答，只有整段都缺资料时才不调模型。工期是制作耗时，不是到货；问收到又没有物流时效时不能用工期去顶。综述要留附加费和范围，不把刚说过的在售再填一遍。`--subset deep` 是另一组深测，204 轮通过不等于语义全部正确。问标价、最低价或沿用旧价时核对金额；包邮会改实付，所以报价里要出现。不寄实物、网盘发码、自提只在问邮寄或把情况和价格一起说时核对，不要求每句价格都带同一串。说成包邮、把 200 元说成 150 元或答应低价，断言仍失败。多轮套件在 `kefu_offline/fixtures/sim_logic_suite.py`。`python -m kefu_offline --reeval 原日志.jsonl --reeval-out 新报告.json` 只重读 checkpoint，不调模型，不改原日志。云端的 `--fake-model` 不是 Mac 网关实测。

成功时进程退出码是 0，输出里 `model_invoked` 为 true，`send_allowed` 和 `transport_send` 为 false，`xianyu_transport` 为 `isolated`。草稿同时出现在终端和 `data/kefu_mac_preview.jsonl`。模型超时、连接失败或坏响应时退出码是 1，并保留规则草稿。缺少上述环境变量时退出码是 2，不会发请求。

这次预览用的商品是 `kefu_offline/fixtures/mac_preview_catalog.yml` 里的「模拟验收商品」，标价 15 元、包邮，范围是一句预览说明。它不是在售商品，也不会写进 `kefu_catalog.yml`。

待审列表：

```bash
KEFU_REVIEW_PATH=data/kefu_mac_preview.jsonl python -m kefu_offline --list-reviews
```

服务启动后也可以看 `GET /api/kefu/reviews`。这个接口不发送。

## 已在当前仓库验证

- `extract_item_id_from_message` 对同时带发送者 ID `2207836320265` 和 URL 商品 ID `100200300400` 的消息返回商品 ID。列表包裹的消息也能读到 URL 里的商品 ID。
- 识别不到商品时不再生成 `auto_用户_时间`。`handle_message` 会把这条消息送进待审，原因是 `unknown_item`。本地数据库没有商品时，Bridge 消息带 `needsHuman: true`，不再静默丢掉。
- 插件入站正文由 `buyerVisibleBody` 带上商品 ID。未确认商品会写明需要人工。`delivery` 不是 `send` 时，入站处理不调用发送。
- `XianyuLive.handle_message` 配上假 WebSocket 的集成测试：模拟消息能答出目录里的 15 元和范围，数据库里的 28 元测试商品也能答出价格和标题。假连接里没有 `MessageSend`。
- 已填写的价格和范围会直接写进草稿。买家原文里的「1元」「支持退款」不会变成草稿。模型候选如果带出资料里没有的价格、退款或工期，会被丢掉，规则草稿留下。
- 本机假的 OpenAI 兼容服务验证了真实 HTTP 客户端：正常 JSON 会采用，坏 JSON 和超时会记成 `bad_response` / `timeout` 并回退到规则草稿。
- 规则回放 15 条失败数为 0。相关 pytest 21 项通过。Node 对入站商品上下文的 2 项测试通过。
- 云端执行 `python -m kefu_offline --mac-preview` 时没有模型环境变量，退出码 2，没有向 `127.0.0.1:3425` 发请求。

## 不能称为已经跑通的最后一环

- 没有在这台云端机器上调用 Mac 的 `http://127.0.0.1:3425/v1`。父需要在 Mac 上执行上面的命令，才算本机模型预览验收。
- 没有连接真实闲鱼，没有用真实买家消息跑 `handle_message`。
- `kefu_catalog.yml` 的 `items` 仍是空的。真实商品 ID、范围、工期、型号、成色、底价、退换规则没有填，程序不会用模拟资料代替这些承诺。

## 父在 Mac 上还要落实的配置

1. 按上面的命令做一次 `--mac-preview`。密钥只用环境变量。
2. 把真实、并且愿意对买家说的商品资料填进 `kefu_catalog.yml`。不知道的字段继续留 `null`。模板见 `kefu_catalog.example.yml`。
3. 不要设置 `XIANYU_ALLOW_SEND`。默认 `KEFU.delivery` 是 `preview`。
4. 真实闲鱼 Cookie 只在以后决定连接平台时才需要，这次预览不需要。

旧的 `global_config.yml` 默认回复文案里仍有「可以直接申请退款」。待审路径不使用这句。`Start.py` 启动时会说明未允许发送。

仓库里没有 `safari_token.py`，也没有 launchd 配置。这不是那套旧本机定制的找回。
