# 逐帧证据与渲染验收

把「解码正常」「逐帧画面正确」「实时观看顺畅」分开记录；三者不能互相代替。
工具需要 Python 3.9+、Pillow 9.1+，以及 PATH 中的 ffmpeg / ffprobe。
所有索引从 0 开始；本工具的 atlas 页范围和 `--allow` 终点包含在内。
分镜表的 `end_frame_exclusive` 仍是排他边界，转换为本工具范围时终点减 1。
命令不需要固定帧率或项目目录。

## 提取所有帧

```sh
python scripts/frame_review.py extract reference.mov review/reference
python scripts/frame_review.py extract native-review.mov review/native
```

输出目录必须不存在或为空；非空目录会被拒绝，避免旧图片混入新证据。
失败的部分输出保留供排错，再提取时选择一个新目录。
不设置输出帧率，不跳帧，不按固定秒数抽样；VFR 时间戳保留在 manifest 中。
只提取第一条视频流，关闭自动旋转，输出其编码栅格；旋转元数据保留在 stream 中。
逐帧 PNG 是无损的解码图，不等于原压缩数据；atlas JPEG 只供索引和浏览。
manifest 记录流帧率、time_base、实际帧数、逐帧 PTS、哈希和连续 atlas 页范围。
默认每页 30 张只是一项排版参数，不表示源片每秒 30 帧。
可用 `--page-frames 24 --columns 6 --thumb-width 360` 调整页密度。

## 时间与切点

先查源片和最终合成的 fps、time_base、起始 PTS；不要从文件名推断帧率。
恒定帧率且起始时间一致时，可用 `t = frame / fps` 表示时间。
VFR 必须读取逐帧 PTS；不要用平均帧率乘时间回推所有帧。
原片与最终片 fps 不同时，记录每个重要切点的源 PTS 和目标帧映射。
目标帧可取最接近目标时间的帧，但要注明舍入策略和误差；不能宣称逐帧一一对应。
单帧语义与时长可能冲突：24 fps 的一帧是 1/24 秒，30 fps 的一帧是 1/30 秒，无法同时保持。
若用户明确要求“只有一帧倒色”，应在目标时间轴重建一帧事件，并记录时长与起点误差。
例如用最近帧、半帧向后舍入，源 f1 的 1/24 秒映射到目标 f1 的 1/30 秒，开始提前约 8.333 ms。
普通 fps 重采样可能把某个源单帧重复成两个目标帧；不能只转码就声称短帧 MG 已复刻。
把连续范围写为例如 `813–832 inclusive`，总数是 `832 - 813 + 1`。
持续 1–6 帧的事件要分别记入场、落定、保持、退出与内部硬切，不能被每秒截图略过。
按连续分区分工审阅，记录已看页与原尺寸补看帧；分区之间检查前后边界。
atlas 能发现运动结构；脸、字形、遮罩边缘和 1px 裁切需要原尺寸帧确认。
不要以图层数、关键帧数量或「没有报错」代替画面质量。

## 精确比较版本

```sh
python scripts/frame_review.py compare review/before review/after --report review/diff.json
python scripts/frame_review.py compare review/before review/after --allow 813:832 --allow 855:874 --report review/diff-allowed.json
```

比较同索引帧，但不进行重采样或自动对齐。帧数、时间基准、帧率或 PTS 不一致会明确报告。
时间不兼容时，差异标为 `timing_unverified`，不能依据 `--allow` 视为已经对齐。
`changed` 保留全部变化，包括只有一个像素或一个通道数值改变的情况。
`--allow` 只是将计划修改范围标为 expected，不会删除或掩盖范围内外的差异。
统计在 RGB8 中计算；PNG 字节不同但 RGB8 相同记为 `bytes_only_in_rgb8`，尺寸不同单列。
字节差异可能来自编码、元数据、透明度或高位深精度，仍保留；高精度色彩需专门检查。
PNG 与提取时哈希不一致会记为 integrity issue，避免把人工改图当成新的原生渲染。
退出码：0 为检查通过；2 表示时间不兼容、意外变化、完整性问题或解码验证失败；1 为执行/输入错误。
完整报告仍应阅读，不能只看退出码。compare 不证明 expected 区域视觉正确。

## 继承已经检查的段落

只有时间轴相同、逐帧像素一致、素材来源可追溯时，才能继承上版某段的逐帧视觉结论。
保留之前的审查范围、报告和本次哈希比较证据，明确本轮实际重看范围。
即使预定只改两层，也要查完整输出的 unexpected 列表；其他合成可能被旧工程覆盖。
若日志显示改动成功而输出像素未变，先核对保存项目、重新打开后的属性与渲染输入。
项目名、日志 SUCCESS、文件更新时间都不足以单独证明修正已进入画面。
不同有损编码可能让许多帧像素略变；这些差异仍保留，不能据此继承像素一致的结论。
必要时直接比较同种设置的原生 AE 无损/中间渲染，编码后的交付视频另验。

## 完整解码与交付编码

```sh
python scripts/frame_review.py verify native-review.mov --report review/native-decode.json
python scripts/frame_review.py verify delivery.mp4 --report review/delivery-decode.json
```

verify 完整解码第一视频流和全部音频流，记录 ffmpeg 错误及实际输出帧数。
帧数与 ffprobe 全解码计数、容器声明值（可用时）分别核对，不用时长乘 fps 代替。
报告保留音轨数量、采样率、声道等流信息；无音轨可能是刻意的 picture-only 输出。
音轨存在或能够解码不等于音画同步、响度正常，仍要实际试听。
黑帧检测只列候选：默认 98% 像素低于亮度 32；黑场、淡出或设计停顿不自动删除。
HDR、色彩范围和曝光可能影响黑帧判断；候选必须回到画面确认。
原生 AE 渲染用于检查合成、遮罩、字层、模糊与运镜；编码输出用于检查压缩、色彩、音轨和容器。
逐帧检查不能证明实时播放流畅：还需用实际播放速度检查节奏、抖动、模糊和音画关系。
报告只写实际做过的检查；未实时播放时明确记录，不能把浏览 atlas 写成完整播放验收。
