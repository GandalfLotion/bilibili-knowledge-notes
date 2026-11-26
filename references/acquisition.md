# 获取字幕与持久登录

## 实现边界

已提供：B站 BV 链接/指定分 P → 播放器字幕轨道 → 中文字幕文字和时间轴；专用 Playwright 浏览器数据目录复用；简体输出。现成字幕不需要 ffmpeg、OCR、语音模型或云端 API。

小红书、抖音：提供独立浏览器登录入口，但未实现专用字幕提取接口。微信视频号：尚无已验证适配，不能把视频号助手账号等同于观看权限。其他平台先检测现有下载工具的字幕能力；失败如实返回，不声称支持。短链接先用可用浏览器或工具解析，保留分集参数，禁止把未经核对的重定向域名当成目标平台。

## 环境按需准备

已有字幕和有效缓存优先复用，可直接进入写笔记环节。需要 B 站专用浏览器登录或在线取字幕时，Playwright 是必需依赖，没有跳过安装的降级路径。**当前任务能调用兼容 Python 时直接复用即可**（3.10+，随包离线 wheel 还需 CPython 3.13）；WorkBuddy 通常自带托管运行时，但把本目录当独立 CLI 跑或换用别的 Agent 时，需自行确认环境里有可用的 Python。所有命令用同一个解释器，装错环境会表现为「明明装好了却报未安装 Playwright」。

先运行 `python bootstrap.py --doctor`（纯标准库、零依赖、不安装任何东西）查看 Python 版本与解释器路径、Playwright、系统浏览器与登录档案状态。缺少依赖时运行 `python bootstrap.py`：优先使用 `wheels/` 中的离线 wheel，其次依次尝试多个短超时镜像；全程不下载浏览器。随包离线 wheel 只匹配 Windows x64 的 CPython 3.13，其他环境由 pip 在线解析或使用对应环境生成的离线包。浏览器直接复用系统已安装的 Chrome/Edge，脚本会自动探测。**不要执行 `python -m playwright install chromium`**：那会下载 150MB+ 二进制，是安装卡顿的主要来源。不安装全部转写依赖。

非 Windows 系统生成简体字幕需已有 OpenCC，缺少时按需安装 `opencc-python-reimplemented`；Windows 使用系统字形转换。它只改字形，不纠错。

## 首次获取与登录

所有命令使用同一解释器。显式 `--channel` 优先，否则复用该平台上次成功取得字幕的通道；没有历史时自动探测系统已安装的 Chrome/Edge 并复用。若历史通道指向 Playwright Chromium 但对应二进制已不存在，自动模式会降级到检测到的系统 Chrome/Edge（通道不同可能需要重新登录）；两者都不可用时给出明确报错，**绝不下载浏览器二进制**。缓存命中或关闭登录窗口不更新偏好。默认数据根目录为用户目录下 `.video-knowledge-notes`，可用环境变量 `VKN_DATA_DIR` 指定独立位置。非敏感通道偏好保存在 `preferences/平台.json`；每个平台的登录数据独立保存，不在技能包或知识库中。禁止指向日常浏览器的默认用户目录，不并发打开同一专用档案。

```text
python -X utf8 SKILL_DIR/scripts/browser_subtitles.py fetch "https://www.bilibili.com/video/BVxxxxxxxxxx/?p=1" --output OUT/sources
```

先尝试获取。若失败且已知另一个专用通道曾成功，可显式切换一次；不要遍历日常浏览器或无限重试。仍需登录时，告知用户“将打开专用浏览器，请在网站正常登录；以后有效期内复用”。用户同意后运行（CHANNEL 必须是此次选定的通道）：

```text
python -X utf8 SKILL_DIR/scripts/browser_subtitles.py login bilibili --channel CHANNEL
```

这是用户需要操作的可见窗口；后台命令保持运行并向用户提示。用户登录后关闭这个专用窗口，脚本结束；默认最多等待5分钟。关闭窗口只表示本轮操作结束，不证明登录成功，之后重新执行 fetch 验证。正常登录持久 Cookie 留在本机，某些会话仍可能在关窗或过期后失效。

小红书/抖音可分别用 `login xiaohongshu`、`login douyin` 保存会话，但不得将此当成字幕提取已支持。不要为了“配置完成”就让用户登录所有平台。

## 状态路由

- `ok` / `cached`：检查文本后写笔记，不转写。
- `login_required`：按需正常登录，不自动读取其他浏览器凭据。
- `request_failed`：可能是网络、风控或接口变化；停止，保留状态，不声称无字幕。
- `no_chinese_subtitles`：接口已确认登录但没有中文字幕；询问是否使用备用转写。
- `unsupported_platform`：当前适配不足；可用已有合法工具或请用户提供媒体/字幕，不混称“没有字幕”。
- `browser_unavailable`：检查 Playwright、指定浏览器是否安装，档案是否被另一个实例占用；不自动删除档案。
- `invalid_subtitle` / `output_conflict`：校验或文件冲突；不覆盖用户成果。
- `simplifier_required`：缺简体转换依赖，未生成成果，按需安装。

## 网络与隐私

脚本默认继承正常网络环境。只有用户希望本次浏览器直连时加 `--direct`（login/fetch 保持一致）：仅影响此浏览器进程，不改系统代理；不能绕过系统级 VPN/TUN 路由，也不保证消除平台风控。不要试图通过关闭安全防护或绕过验证码解决问题。用户在 WorkBuddy 的正常网络环境完成真实测试。

登录凭证不输出、不截图二维码给第三方、不上传、不打包。浏览器数据包含敏感信息，不是加密保险箱，应放在仅本机用户可访问、非同步目录。默认没有 Cookie 导出步骤。用户主动提供 Cookie 文件时可由已支持该格式的工具读取，不默认扫描磁盘。账号退出/删除数据需用户明确要求。

技术依据：[Playwright持久浏览器](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context)、[共享Cookie的请求上下文](https://playwright.dev/python/docs/api/class-apirequestcontext)。接口可变化，成功需实际测试。
