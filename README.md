# 文本转语音 · 视频合成

输入一段文本 → 自动配音（Edge TTS 中文语音）→ 按关键词把语音插入指定视频的音轨。

## 换一台电脑运行（首次）

1. **装 Python 3.10+**：<https://www.python.org/downloads/> ，安装时务必勾选 **Add python.exe to PATH**
2. **拿到代码**：`git clone <仓库地址>`，或在仓库页面点 **Code → Download ZIP** 后解压
3. **双击 `启动.bat`**（macOS / Linux 用 `./启动.sh`）

首次运行会自动创建 `.venv` 虚拟环境并安装依赖（1~3 分钟，需联网），装完浏览器自动打开 `http://127.0.0.1:8765`。
之后每次直接双击即可，不再重复安装。依赖装在项目内的 `.venv` 里，不会污染系统 Python。

> 依赖装不上时脚本会自动改用清华镜像重试。仍失败就手动执行：
> `pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`
>
> 环境是否有问题，先跑 `python 自检.py`，它会逐项检查 ffmpeg / 编码器 / 中文字体 / 素材 / 网络并给出处理办法。

## 路由规则

规则放在 **`rules.json`** 里，改这个文件就行，不用动代码。

| 关键词 | 目标素材 |
|---|---|
| `大雾` | `Downloads\大雾.mp4` |
| `雷电` | `Downloads\雷电.mp4` |
| `大风` | `videos\大风.mp4`（**待放入素材**） |

- 命中一个关键词 → 产出一个成片
- 命中多个 → **同时产出多个版本**
- 一个都不命中 → 拒绝并提示当前有哪些关键词可用
- 命中但视频文件不存在 → 明确提示缺哪个文件、该放到哪里

## 怎么新增一个关键词（例如“暴雨”）

1. 把对应的视频文件放到 `app\videos\` 目录里，例如 `app\videos\暴雨.mp4`
2. 用记事本打开 `app\rules.json`，在 `rules` 里照着已有条目复制一份，改成：

```json
{ "keywords": ["暴雨"], "video": "videos/暴雨.mp4", "label": "暴雨", "tag": "暴雨" }
```

3. 保存后回到网页，点右上角的 **「重载规则」**（或直接刷新页面）即可生效，**不需要重启服务**

字段说明：

| 字段 | 说明 |
|---|---|
| `keywords` | 关键词列表，命中**任意一个**即触发该视频。可写同义词，如 `["大风","阵风","强风"]` |
| `video` | 视频路径。可写完整路径（如 `C:/素材/暴雨.mp4`），也可写成相对 `app` 目录的路径 |
| `label` | 网页上显示的名字，可省略（默认取第一个关键词） |
| `tag` | 输出文件名里的标记，可省略 |

> 网页上点「打开配置文件」可以直接定位到 `rules.json`；
> 关键词卡片出现「视频缺失」说明该视频还没放到对应位置，补上文件后点「重载规则」即可。

## 预警图标（左上角叠加）

`rules.json` 里的 `signals` 段：文本包含图标关键词时，把对应 GIF/PNG 图标叠加到**成片左上角**。

```json
"signals": [
  { "keywords": ["大雾黄色"], "icon": "signals/FOGW_Y.gif", "label": "大雾黄色预警" },
  { "keywords": ["大雾橙色"], "icon": "signals/FOGW_O.gif", "label": "大雾橙色预警" }
]
```

- 图标文件放在 `app\signals\` 目录（已内置大雾黄/橙两个，还放了风、雨、雷电等备用图标）
- **归属自动判断**：图标关键词里包含哪个视频的关键词（如「大雾橙色」包含「大雾」），就贴到哪个视频的成片上；也可以加 `"attach": "大雾"` 手动指定
- **改图标大小 / 位置**：在该条 signal 里配置（都是相对画面的比例，改完点「重载规则」生效）
  - `"size": 0.33` — 图标宽度占画面宽度的比例（默认 0.33，即 33%，范围 0.05~0.5）
  - `"margin_x": 0.05` — 距左边缘，占画面宽度（默认 0.05）
  - `"margin_y": 0.08` — 距上边缘，占画面高度（默认 0.08）
  - `"margin": 0.06` — 简写，同时设定距左、距上
  - 命令行对应 `--signal-size`、`--no-signal`
- 图标与画面文字可同时使用；图标需要重编码，4K 素材会慢一些
- 新增图标（如暴雨橙色）：把 GIF 放进 `signals\`，在 `signals` 段复制一条改关键词和文件名即可

## 语音引擎

默认使用 Edge 朗读（微软在线 TTS，免费、无需密钥，音质与 Azure TTS 同源，14 个中文音色）。
引擎写在 `tts_config.json` 的 `engine` 字段里。

> Edge 是非官方接口，依赖微软服务可达。国内网络一般正常，若失效可看下面「换用其他云端引擎」。

### 换用其他云端引擎

语音合成已抽成可插拔适配层（`tts.py`）：继承 `Provider` 实现 `ready()` / `voices()` / `synth()` 三个方法，
加进 `PROVIDERS` 列表并在 `tts_config.json` 里把 `engine` 指过去即可，`core` / 网页 / 命令行都无需改动。
若引擎需要密钥，建议在 `tts_config.json` 里加一个专属配置段存放，并用环境变量覆盖以便容器部署。


## 启动

### Windows

双击 **`启动.bat`**，浏览器会自动打开 `http://127.0.0.1:8765`（端口被占用时自动顺延）。
关闭命令行窗口即可停止服务。

脚本会依次：找目录内的 `.venv` → 没有就用系统 Python 建一个 → 检查依赖、缺了自动装 → 启动服务。
**不依赖任何写死的路径**，整个文件夹拷到别的电脑也能直接用。

### Linux / macOS

```bash
cd app
chmod +x 启动.sh
./启动.sh                 # 默认 8765 端口，只监听本机
HOST=0.0.0.0 ./启动.sh    # 允许局域网其他机器访问
NO_BROWSER=1 ./启动.sh    # 服务器环境，不自动打开浏览器
```

也可以直接运行：`pip install -r requirements.txt && python app.py`（`Ctrl+C` 停止）。

**Linux 上要先装好三样东西**（缺一样都会在自检里报出来）：

```bash
sudo apt install ffmpeg fonts-noto-cjk    # Debian/Ubuntu
sudo yum install ffmpeg google-noto-sans-cjk-fonts   # CentOS/RHEL
```

- `ffmpeg`：音视频处理。程序优先用 `imageio-ffmpeg` 自带的二进制，若它不带 libx264/aac 会自动改用系统的 ffmpeg
- **中文字体**：画面文字必须用中文字体，否则会渲染成方块（这是 Linux 上最常见的问题）。装完执行 `fc-cache -fv`
- 若系统 locale 不是 UTF-8，成片的中文文件名会失败——`启动.sh` 已设置 `PYTHONUTF8=1`，手动运行 `python app.py` 时请先 `export PYTHONUTF8=1`

不确定环境是否齐备，先跑一次自检：

```bash
python 自检.py     # 检查 ffmpeg/编码器/中文字体/规则/素材/网络，逐项给出处理办法
```

**把素材迁到 Linux**：`rules.json` 里的 Windows 路径（如 `C:/Users/.../大雾.mp4`）在 Linux 上不存在时，
会自动回退到 `app/videos/` 目录下的同名文件。所以最简单的做法是——把整个 `app` 目录连同 `videos`、`signals`
一起拷到 Linux，视频放在 `videos/` 里即可，无需改配置。

## 界面功能

- **实时关键词检测**：输入框下方的卡片会高亮命中的关键词，并显示素材分辨率与时长；命中预警图标时会在标题旁提示
- **预警图标叠加**：文本含「大雾黄色」「大雾橙色」等关键词时，对应预警标志自动叠加到成片左上角（大小与边距在 `rules.json` 的 signals 里配置）
- **右上角标题**：自动从文本开头提取「XX气象台…发布XX预警信号」，
  如「磁县气象台2026年10月31日17时39分发布大风蓝色预警信号：…」提取为「磁县气象台发布大风蓝色预警信号」，
  平均分成两行、右对齐贴在右上角（白色粗体黑描边、无底板，可在界面上关闭；开头没有气象台署名时自动不显示）
- **发布日期**：自动提取文本开头的发布日期（如「2026年10月19日」），
  金色黑描边、水平居中显示在标题块下方，并自动避开左上角图标；提取不到日期就不显示
- **画面文字叠加**：输入的文本以白色文字、黑色描边显示在画面底部（左对齐、无底板）；自动换行（均衡排版、行首标点禁则）、字号三档可调，随画面尺寸自适应缩放；可在界面上关闭
- **8 种中文语音**：晓晓 / 晓伊 / 云希 / 云健 / 云扬 / 云夏 / 晓北 / 晓妮
- **语速 / 音量** 调节（−50% ~ +100%）
- **试听**：只合成语音、不生成视频
- **右上角标题开关**：默认开启，自动提取、无需填写
- **音画对齐策略**
  - 语音长于视频：循环画面（流拷贝，秒级出片）／定格最后一帧（需重编码）
  - 语音短于视频：保留完整画面并补尾部静音／把画面裁到语音长度
  - 输出清晰度：原始 / 1080P / 720P
- **结果区**：在线预览、下载、复制链接；下方为历史文件列表

快捷键 `Ctrl + Enter` 直接生成。

## 命令行用法

```bash
python core.py --text "邢台市气象台发布大雾橙色预警，请注意行车安全"
python core.py --text "午后有雷电" --voice zh-CN-YunyangNeural --rate +10 --resolution 1080
python core.py --text "今夜有大雾" --engine edge --voice zh-CN-YunyangNeural  # 指定引擎与音色
```

参数：`--voice --rate --volume --overflow {loop,freeze} --underflow {pad,trim} --resolution {source,1080,720} --no-caption --no-signal --no-title`

## 目录结构

```
app/
├── app.py          FastAPI 服务（异步任务 + 结果文件）
├── core.py         TTS、关键词路由、ffmpeg 合成逻辑
├── tts.py          可插拔语音引擎适配层（当前内置 edge）
├── caption.py      画面文字叠加（换行算法 + drawtext 滤镜：底部正文/右上标题/日期）
├── rules.json      ★ 关键词 → 视频 路由表 + 预警图标表（改这里就行）
├── tts_config.json ★ 语音引擎配置
├── videos/         放视频素材的目录（rules.json 里可用相对路径引用）
├── signals/        放预警图标（GIF/PNG）的目录
├── static/index.html   界面
├── outputs/        生成的成片
├── 启动.bat        Windows 启动脚本
├── 启动.sh         Linux / macOS 启动脚本
├── 自检.py         环境自检（ffmpeg / 字体 / 规则 / 网络）
└── requirements.txt    依赖清单
```

程序本身是纯 Python，Windows / Linux / macOS 通用；音视频与合成全部走 ffmpeg，无平台专属调用。

## 技术说明

- 语音：Microsoft Edge TTS（`edge-tts`），无需 API Key
- 音视频：`ffmpeg`（`imageio-ffmpeg` 内置二进制）
- 画面文字：`drawbox`（半透明灰底）+ `drawtext`（微软雅黑粗体，每行一个 `textfile`，避免中文标点转义问题）
- 预警图标：GIF 作为独立输入，`scale` + `overlay` 贴到左上角，宽度按画面宽度比例自适应
- 不加文字/图标且不改清晰度时视频流**直接拷贝**（`-c:v copy`）不重编码，1080P 素材约 0.5 秒出片，画质零损失；
  叠加文字或图标后需重编码（1080P 约 15~20 秒，4K 约 2~4 分钟）
