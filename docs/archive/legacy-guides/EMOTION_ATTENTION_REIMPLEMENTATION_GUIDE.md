# 情绪分析与注意力分析复现说明

## 1. 文档目的

本文描述当前项目中情绪分析和注意力分析的实际计算方法，供另一个 AI 在其他项目中按相似方案进行大致复现。

> **当前事实**：两类分析都在浏览器端从摄像头低频采样帧中提取特征，后端只接收结构化描述符并完成观测存储、质量标记和聚合。默认分析描述符不包含原始图片或 Base64 帧。
>
> **边界**：本方案是教育训练 Demo 的轻量级行为观测，不是临床诊断、精确眼动、视线落点检测或经过人群校准的情绪识别模型。

## 2. 总体技术方案

```text
浏览器摄像头
  -> 160 x 120 Canvas，默认每秒采样 1 帧（允许 0.2~2 FPS）
  -> JPEG/WebP 压缩帧，仅用于浏览器内分析
  -> 人脸检测
       1. 优先浏览器原生 FaceDetector
       2. 不可用时使用 MediaPipe Face Detector
  -> 注意力：人脸框几何规则评分
  -> 情绪：MediaPipe Face Landmarker blendshape 规则评分
  -> 发送 visualFeatures + emotionFeatures 等描述符
  -> 后端生成 observation，按题目和会话聚合
  -> 监控台展示实时值，训练报告展示曲线与汇总
```

主要依赖为 `@mediapipe/tasks-vision 0.10.14`。当前实现通过 CDN 加载 MediaPipe WASM、BlazeFace short-range Face Detector 和 Face Landmarker 模型；离线项目应把这些资源部署到本地静态目录。

## 3. 注意力分析

### 3.1 定义

本项目把“单张脸是否位于画面中合理的位置和大小”作为“面向屏幕/任务参与”的代理。算法版本为 `browser-attention-v2`。

它没有估计瞳孔方向或真实头部欧拉角。`left/right/up/down` 是根据人脸框中心相对画面中心的位置推断的粗粒度方向。

### 3.2 输入特征

- 帧宽、高；默认 `160 x 120`。
- 检出的人脸数量 `faceCount`。
- 最大人脸框 `primaryFace = {x, y, width, height}`。
- 图像质量 `good | low_light | blurred | occluded | unavailable`。

当前图像质量是压缩大小启发式规则，而不是真正的亮度/模糊检测：

```text
bytesPerPixel = compressedBlobSize / (frameWidth * frameHeight)

blobSize == 0        -> unavailable
bytesPerPixel < 0.02 -> low_light
bytesPerPixel < 0.05 -> blurred
其他                  -> good
```

> **建议**：新项目可以先复现此规则以保持行为相似，后续再用平均亮度、拉普拉斯方差和遮挡检测替换；替换后应升级算法版本。

### 3.3 单帧注意力分数

首先计算归一化几何量：

```text
centerX = (face.x + face.width / 2) / frameWidth
centerY = (face.y + face.height / 2) / frameHeight

offsetX = clamp((centerX - 0.5) * 2, -1, 1)
offsetY = clamp((centerY - 0.5) * 2, -1, 1)

faceAreaRatio = clamp(face.width * face.height / (frameWidth * frameHeight), 0, 1)
```

然后计算三个子分数：

```text
centerScore = clamp(1 - sqrt(offsetX^2 + offsetY^2) / 0.95)

idealArea = 0.14
if area <= 0: areaScore = 0
else if area < 0.025 or area > 0.42: areaScore = 0.25
else: areaScore = clamp(1 - abs(area - idealArea) / idealArea)

aspectRatio = face.width / face.height
if aspectRatio < 0.55 or aspectRatio > 1.65: aspectScore = 0.35
else: aspectScore = clamp(1 - abs(aspectRatio - 1) / 0.8)
```

最终分数：

```text
geometryScore = 0.55 * centerScore
              + 0.25 * areaScore
              + 0.20 * aspectScore

multiFacePenalty = 0.45 if faceCount > 1 else 1.0
facingScore = clamp(geometryScore * multiFacePenalty)   # 0~1

roughlyFacingScreen = (faceCount == 1 and facingScore >= 0.55)
attentionScore100 = round(facingScore * 100)            # UI/报告常用 0~100
```

无脸、无主脸框或图像不可用时，`facingScore = 0`，方向为 `unknown`。多脸时即使几何位置良好，也不会被标为面向屏幕。

### 3.4 粗粒度方向

```text
if roughlyFacingScreen: orientation = screen
else if abs(offsetX) > abs(offsetY):
    offsetX <= -0.12 -> left
    offsetX >=  0.12 -> right
else:
    offsetY <= -0.12 -> up
    offsetY >=  0.12 -> down
otherwise -> away
```

### 3.5 置信度与质量

图像质量基础置信度：`good=0.88`，`low_light=0.58`，`blurred/occluded=0.48`，`unavailable=0`。

```text
confidence = clamp(
  qualityConfidence * (0.45 + 0.55 * facingScore) * multiFacePenalty
)
```

- `unavailable` -> `missing_device`。
- `low_light/blurred/occluded` 或 `confidence < 0.5` -> `low_confidence`。
- 其他 -> `complete`。

注意：图像质量只影响 `confidence` 和质量状态，不直接降低 `facingScore`。

### 3.6 按题目和会话聚合

每个采样帧在当前实现中记为 `durationMs = 1000`。

- 单题注意力：该题所有有效 `facingScore` 的算术平均值，再乘 100。
- 单题质量：无样本为 `insufficient`；任一样本降级则为 `partial`；否则为 `complete`。
- 会话朝屏比例：`screenOrientedMs / totalObservedMs`。
- 报告注意力维度：各题注意力分数的算术平均；若整体质量不是 `complete`，再乘 `0.7` 质量系数。
- 报告中低于 50 分的题目会被标为注意力低点。

如果开启了原始视频留存且某题没有成功捕获视频，该题可被标记为 `excluded_no_video` 并从报告注意力平均中排除。这是媒体证据策略，不是注意力算法本身。

## 4. 情绪分析

### 4.1 定义

主路径使用 MediaPipe Face Landmarker 输出的面部 blendshape，再通过固定权重计算三个相对分量：

- `positive`：积极/微笑样表现。
- `focused`：中性、闭口、轻微眯眼所形成的“专注样”表现。
- `frustrated`：皱眉、压嘴、眉部紧张所形成的“受挫样”表现。

算法版本为 `browser-emotion-v1`。这三个分量用于趋势与相对占比，不应解释为真实心理状态或诊断标签。

### 4.2 MediaPipe 配置

```text
任务：FaceLandmarker
runningMode：IMAGE
numFaces：1
outputFaceBlendshapes：true
delegate：优先 GPU，失败后回退 CPU
```

只有注意力人脸检测已判断 `facePresent=true` 时，才运行 Face Landmarker。Landmarker 或模型加载失败时，不生成有效情绪特征，而是由后端记录降级观测。

### 4.3 单帧情绪计算

所有 blendshape 输入先截断到 `[0, 1]`；左右特征取平均：

```text
smile       = avg(mouthSmileLeft, mouthSmileRight)
cheekRaise  = avg(cheekSquintLeft, cheekSquintRight)
frown       = avg(mouthFrownLeft, mouthFrownRight)
browDown    = avg(browDownLeft, browDownRight)
browInnerUp = avg(browInnerUpLeft, browInnerUpRight)
eyeSquint   = avg(eyeSquintLeft, eyeSquintRight)
mouthPress  = avg(mouthPressLeft, mouthPressRight)
jawOpen     = jawOpen
```

原始分数公式：

```text
positive = clamp(
  0.72 * smile + 0.18 * cheekRaise + 0.10 * (1 - frown)
)

frustrated = clamp(
  0.42 * frown + 0.34 * browDown
  + 0.14 * mouthPress + 0.10 * browInnerUp
)

neutralFocus = clamp(1 - 0.35 * jawOpen - 0.25 * frustrated)

focused = clamp(
  0.55 * neutralFocus + 0.25 * eyeSquint + 0.20 * (1 - positive)
)

signalStrength = max(positive, focused, frustrated)
confidence = clamp(
  0.35 + 0.45 * signalStrength + 0.10 * (smile + eyeSquint)
)
```

随后把三个分数归一化为比例：

```text
total = positive + focused + frustrated
if total <= 0.05:
    positive = focused = frustrated = 0
else:
    positive   /= total
    focused    /= total
    frustrated /= total
```

最终保留三位小数。监控界面的主标签取三个归一化分数中的最大值。

### 4.4 情绪质量与聚合

- 无人脸或无 blendshape：记录 `face_absent` / `emotion_unavailable`，质量为 `insufficient` / `missing_device`。
- 有特征但 `degraded=true` 或 `confidence < 0.45`：质量为 `low_confidence`。
- 其他：质量为 `complete`。
- 报告至少需要 2 个可用情绪观测，否则返回 `INSUFFICIENT_SIGNALS`，不输出可用情绪占比。
- 会话情绪：分别对全部可用帧的三个分数求算术平均，再归一化，使三项之和约为 1。
- 实时监控可只取最近 12 个有效观测求均值，以减少短时抖动。

### 4.5 启发式后备路径

项目还保留了一个不使用人脸特征的 `heuristic` 后备方案。它用答题正确率、错误次数、朝屏比例和语言响应情况估计三个值：

```text
positive   = 0.35 + 0.35 * firstTryAccuracy + (responseCount > 0 ? 0.10 : 0)
focused    = 0.25 + 0.45 * screenOrientedRatio
frustrated = 0.35 * wrongRate + 0.05 * emptyResponses + 0.08 * repeatedResponses
```

三项同样归一化。该路径始终标记为降级结果，因为它反映的是任务表现推断，不是摄像头情绪观测。

## 5. 推荐的数据结构

前端发送的最小描述符可以设计为：

```ts
interface CameraAnalysisDescriptor {
  sessionId: string;
  questionId?: string;
  frameId: string;
  sequence: number;
  capturedAt: string;
  width: number;
  height: number;
  downsampled: true;
  rawFramePersisted: false;
  visualFeatures: {
    facePresent: boolean;
    faceCount: number;
    faceBox?: { x: number; y: number; width: number; height: number }; // 归一化坐标
    facingScore: number;
    roughlyFacingScreen?: boolean;
    headOrientation: string;
    imageQuality: string;
    confidence: number;
    algorithmVersion: "browser-attention-v2";
  };
  emotionFeatures?: {
    positiveScore: number;
    focusedScore: number;
    frustratedScore: number;
    confidence: number;
    degraded: boolean;
    algorithmVersion: "browser-emotion-v1";
  };
}
```

后端存储时还应加入 `provider`、`dataQuality.status`、`reasonCode`、`degraded` 和算法/模型版本，避免把缺设备、无脸、低置信度误当成儿童“不专注”或“情绪不好”。

## 6. 在另一个项目中的最小复现顺序

1. 用 `getUserMedia({video: true, audio: false})` 获取摄像头，只在 localhost/HTTPS 环境运行。
2. 每秒将视频绘制到一个 `160 x 120` Canvas；避免并发处理尚未完成的帧。
3. 接入 MediaPipe Face Detector，选最大人脸框，按第 3 节公式计算注意力。
4. 在有人脸时运行 Face Landmarker，读取 blendshape，按第 4 节公式计算情绪。
5. 只把结构化特征发送到后端；除非已有同意、留存和删除制度，否则不上传或保存原始帧。
6. 后端按 `sessionId + questionId` 保存观测并聚合，始终携带质量与降级状态。
7. UI 使用最近若干帧的移动平均；报告使用按题/会话聚合值，不用单帧标签下结论。
8. 至少为“正中单脸、偏侧单脸、多脸、无人脸、摄像头不可用、微笑、皱眉、Landmarker 失败”建立固定测试样例。

## 7. 必须保留的解释边界

- 注意力分数实际表示“面部几何上大致朝向屏幕”，不表示认知注意、理解程度或眼睛注视点。
- `focused` 情绪分量和注意力分数来自不同规则，不应合并成一个临床意义上的专注指标。
- 当前阈值和权重是 Demo 启发式参数，未经目标人群标注数据校准。
- 多人、遮挡、侧坐、辅助设备、面部运动差异和光照都会造成偏差。
- 新项目若要用于真实儿童，应先完成隐私、安全、公平性和人工标注验证，并保留人工复核入口。

## 8. 当前项目源码索引

- `shared/src/attentionScoring.ts`：注意力公式、阈值、图像质量规则。
- `shared/src/emotionScoring.ts`：blendshape 情绪公式与归一化。
- `frontend/src/features/camera/browserCameraCapture.ts`：摄像头采样、描述符生成。
- `frontend/src/features/camera/mediapipeFaceDetector.ts`：MediaPipe 人脸检测。
- `frontend/src/features/camera/mediapipeFaceLandmarker.ts`：MediaPipe blendshape 提取。
- `backend/src/services/localAttentionObservationProvider.ts`：注意力质量标记。
- `backend/src/services/localEmotionObservationProvider.ts`：情绪质量标记。
- `backend/src/services/attentionScoreUtils.ts`：逐帧到逐题注意力聚合。
- `backend/src/services/emotionFeatureService.ts`：情绪观测聚合。
- `backend/src/services/behaviorAggregationService.ts`：逐题和会话行为摘要。
- `backend/src/services/reportScoringService.ts`：报告注意力维度。

