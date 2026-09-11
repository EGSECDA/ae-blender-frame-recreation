# 从参考视频到可编辑工程

本说明解释 [AE / Blender 逐帧视觉复刻 skill](../SKILL.md) 的使用顺序。命令是可复用入口，镜头、构图和素材需要根据当前项目设计。

## 1. 接手工程并确定时间基准

先找到实际参考视频、最新工程、素材、生成脚本、渲染文件和交付记录。核对主合成、画幅、帧率、总帧数和音轨，不能仅凭文件名中的 `FINAL` 判断最新版本。

把文件分成输入、素材、Blender、AE、输出和审核目录。保留已有版本；每轮补丁写入唯一候选工程，记录本轮使用的路径与哈希。

时间表使用整数帧。主时间轴从 0 开始，镜头范围为 `[start_frame, end_frame_exclusive)`。例如起点 100、终点 116 表示 16 帧。

[example_timeline.json](../assets/example_timeline.json) 展示了镜头、内部事件、保护区域和序列映射；其中数字是演示数据，不是案例影片的完整分镜。

## 2. 连续提帧并记录短事件

在仓库根目录运行：

```sh
python scripts/frame_review.py extract reference.mp4 review/reference
```

输出包含全部解码帧、连续 atlas 和 manifest。它不按固定秒数采样，不强制转换帧率；VFR 的逐帧时间戳也会保留。输出目录必须为空或不存在。

先从 atlas 找到切点和运动结构，再以原尺寸看文字、脸部、蒙版边缘和短闪帧。为每个镜头记录：

| 事件 | 观察内容 |
|---|---|
| 预备 | 元素是否先压缩、后退、聚集或停顿 |
| 冲击 | 入场用了几帧，是否倒色、剪影、方向模糊或突然切换 |
| 落定 | 是否过冲，在哪一帧恢复清晰和可读 |
| 保持 | 微动、镜头推进和背景演出怎样继续 |
| 退出 | 离场与下镜头如何衔接，是否存在只有一帧的中间造型 |

1–6 帧的事件分别登记。不能用一条长缓动曲线替代参考中的连续短事件。

参考和交付帧率不同时，记录源 PTS、目标帧与舍入误差。24 fps 的一帧和 30 fps 的一帧时长不同；用户要求目标片中“只闪一帧”时，应在目标时间轴重建，而不能仅转码后假定相同。

## 3. 划分生成素材、二维动效和三维空间

| 制作位置 | 负责内容 |
|---|---|
| 图像模型 | 角色插画、环境画、纸张纹理和需要的位图变体 |
| After Effects | 原生可读文字、UI、蒙版、人物窗口、对话、色变、模糊和整体合成 |
| Blender | 三维场景、曲面物体、真正的相机运动、透视、受光与景深 |

先安排人物、主标题、辅助信息和前景的阅读顺序，再添加装饰。生成素材应留出构图和裁切空间；角色眼睛、手势及关键文字需要有完整可读阶段。

可参考 [视觉方向](../references/visual-direction.md) 中的素材与构图判断。截图展示的是制作案例，仓库不提供该影片的完整角色原画、参考音乐或工程依赖包。

## 4. 在 AE 中保留编辑能力

### 实际连接方式

AE 自动化使用 JSX / ExtendScript，脚本负责显式打开、修改和另存工程；`aerender.exe` 从明确的 AEP 路径输出画面。以下是调用形式，假定应用程序已加入 PATH，且 `build.jsx` 是当前项目自行编写的构建脚本：

```sh
AfterFX.com -m -noui -r build.jsx
aerender.exe -project project/candidate.aep -comp MASTER -output renders/native-review.mov
```

启动参数、输出模块和效果接口需在本机确认。示例不替你创建 `build.jsx` 或 `MASTER` 合成，也不保证默认输出模块符合交付格式。先枚举并测试目标环境中的输出模板，确认尺寸、通道和音频输出。

本流程无需专用 AE / Blender MCP；两款应用各自使用原生脚本和命令行接口。窗口控制仅辅助检查界面和截图。

### AE 辅助库

[ae_primitives.jsx](../scripts/ae_primitives.jsx) 定义 `AEFrameTools`，加载时不打开、保存或修改当前工程。调用者负责选择正确工程、合成、图层和属性。

例如，已载入库并取得一个二维图层 `layer` 与所属合成 `comp` 后：

```javascript
var position = layer.property('ADBE Transform Group').property('ADBE Position');
AEFrameTools.setKeys(
    position,
    [[0, [-600, 400]], [3, [92, 400]], [5, [80, 400]]],
    comp.frameRate
);
```

这会以整数帧重建该属性的完整关键帧组，重复运行不会累加旧键。它拒绝启用表达式的属性、分离维度的 Position leader 和时间重映射属性；复杂原生值与宿主取值范围仍由调用者验证。详细边界见 [AE 工程说明](../references/ae-engineering.md)。

### 人物框、对白与三维字

- **固定人物框：** 使用固定尺寸的窗口预合成，外层移动窗口，内层移动原画。`addFixedPortraitPanel` 提供基础构造，但不会识别人脸；必须检查全部运动帧中的五官位置与透明留白。
- **多人对白：** 在同一场景内保持每个人的站位。发言状态控制彩色 / 灰阶、亮度和小幅动作。灰阶不等于半透明，左右顺序按当前项目要求设置。
- **三维文字：** 字与底片先在二维预合成中排好，再将整体作为三维面，避免近乎共面的独立图层发生遮挡。检查最近端、最大字号和退出前最后一个可读帧。
- **短帧模糊：** 模糊应服务冲击和速度。落定后恢复清晰，不能把只出现一两帧的关键造型全部抹掉。

每轮只让一个写入者保存 AEP。保存后关闭并重新打开候选文件，读取关键参数确认，再从该路径渲染。`SUCCESS` 日志不能证明新效果已经进入成片。

## 5. 在 Blender 中制作前后层次

先独立运行包内的曲面纸张演示：

```sh
blender --background --factory-startup --python-exit-code 1 --python scripts/blender_paper_demo.py -- --output-dir ./work/paper-demo --fps 30 --frames 72 --burst-frame 28 --render-frames 18,31,48 --resolution-percent 25
```

它通过 Blender 内置的 `bpy` 建立网格、形态键、厚度、材质、相机与动画。这是可控轨迹的技术演示，并非布料物理模拟。默认纸面是占位材质，正式设计可以添加 `--texture ./inputs/paper.png`；纹理会打包进输出 blend。

| 参数 | 意义 |
|---|---|
| `--frames`、`--fps` | 总帧数和实际帧率 |
| `--burst-frame` | 局部时间轴中的爆散首帧 |
| `--render-frames 18,31,48` | 只渲指定小样帧；`all` 渲整段，不填则只建场景 |
| `--resolution-percent` | 小样或正式渲染的分辨率比例 |
| `--width`、`--height` | 三维通道本身的画幅 |
| `--absolute-start-frame` | 局部第 1 帧对应的主时间轴帧号 |
| `--protected-rect NAME:X0,Y0,X1,Y1` | 可重复的构图保护矩形，使用左上为原点的 0–1 坐标 |
| `--strict-protection` | 发现保护区交叠时报告失败；不会自动重排或掩盖物体 |

脚本只允许新的独立后台场景，拒绝覆盖已有输出。每轮测试使用新输出目录。`--python-exit-code 1` 让 Python 失败传递为非零进程退出码。

设计爆散时，先让符纸进入规则阵列、向心聚集并短暂停顿，再在几帧内向镜头爆散，随后显著减速。近景保留少量大纸和适度虚焦，中景至少有一张能看清纸面、印刷及卷边的主体，远景负责空间结构。背景大幻影或颜色变换应与主体阅读顺序协调。

演示的“四帧爆散”指 B、B+1、B+2、B+3 四个采样，首末相隔三个帧间隔；B+4 进入慢漂。具体节奏需按参考重建。

## 6. 透明序列接入 AE

演示输出 `paper_demo.blend`、`renders/paper_XXXX.png`、投影审查和 manifest。PNG 使用 RGBA、16 bit 与透明背景；导入 AE 时核对 Straight Alpha、序列帧率、画幅和首末对应关系。

```text
主时间轴绝对帧 = 主时间轴起帧 + Blender 局部帧 - 1
```

如果多个相邻 AE 段落共享同一序列，后段从前段使用过的帧数继续，避免重新从第 1 帧播放。需要整段倒色或模糊时，让三维纸张参与同一光学预合成，检查色变前后和接镜的连续帧。

几何投影用于查穿镜头和可能的遮挡，真实渲染的 Alpha 用于查模糊尾迹与像素交叠。两者分别记录；三帧小样只能证明那三帧，不能代替整段序列检查。更多细节见 [Blender 深度说明](../references/blender-depth.md)。

## 7. 以实际渲染关闭问题

先从 AE 输出连续测试段，再提取全部帧：

```sh
python scripts/frame_review.py extract renders/before.mov review/before
python scripts/frame_review.py extract renders/after.mov review/after
python scripts/frame_review.py compare review/before review/after --allow 813:832 --report review/diff.json
python scripts/frame_review.py verify renders/delivery.mp4 --report review/delivery-decode.json
```

`813:832` 是示例，包含两端，共 20 帧。替换为当前项目的计划修改范围。`compare` 不自动对齐或重采样；时间戳、帧率或数量不兼容时明确报告，不能把范围标成允许就视作已经对齐。

| 检查 | 能确认什么 | 仍需人工确认 |
|---|---|---|
| 帧比较 | 哪些帧发生变化，是否超出计划范围，提取文件是否被改动 | 变化是否设计得更好 |
| 连续帧查看 | 短闪、文字遮挡、人物出框、局部跳变 | 正常速度下的整体节奏 |
| 全片解码 | 视频与音频流能否完整解码，帧数与流信息 | 音画同步、音量及声音是否完整 |
| 实时观看与试听 | 节奏、模糊、抖动和听感 | 单帧边缘细节需回看原尺寸帧 |

黑帧只作为候选提示，设计黑场不自动删除。脚本退出码 0 表示相应自动检查通过，不能代表画面审核通过；退出码 2 表示检查发现问题，1 表示输入或执行失败。应阅读 JSON 报告中的具体原因。

## 8. 保存与交付

保留清楚的正式 AEP、需要的 Blender 源文件、完整素材、播放文件及审核记录。改动过的连续帧全部复看；只有时间轴与像素一致且来源可追溯的区段，才能沿用之前的审核结论。

应用失败时先保存日志、输入版本和已完成帧，判断问题属于脚本、素材、模板、设备还是应用本身。重启自己启动的失败进程并缩小测试范围，保护用户的未保存 GUI 会话。恢复策略和正式交接内容见 [交付说明](../references/delivery.md)。

这个包的 AE 库已完成语法与 mock 测试，但独立原生宿主测试因启动阶段 GPU 错误未执行。使用新环境时，先做临时小合成与原生短渲染。Blender 已做真实三帧小样检查，整段输出仍需逐帧验收。最终报告应写清实际完成、实际看过和仍未验证的部分。
