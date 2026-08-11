// static/js/pose_similarity.js

// 工具函数
const mid = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);

// 步骤1：归一化（平移/尺度不变）
export function normalizePose(landmarks) {
  // 取左右髋 (23,24) 与左右肩 (11,12)
  const hip = mid(landmarks[23], landmarks[24]);
  const shoulder = mid(landmarks[11], landmarks[12]);
  const torso = dist(hip, shoulder) || 1e-6;

  return landmarks.map(p => ([
    (p.x - hip.x) / torso,
    (p.y - hip.y) / torso
  ]));
}

// 步骤2：相似度（欧氏距离 → 高斯映射）
export function poseSimilarity(normA, normB) {
  const n = Math.min(normA.length, normB.length);
  let sum = 0;
  for (let i = 0; i < n; i++) {
    sum += Math.hypot(
      normA[i][0] - normB[i][0],
      normA[i][1] - normB[i][1]
    );
  }
  const d = sum / n; // 平均点距
  const sigma = 0.6; // 可调参数
  return Math.exp(-(d * d) / (2 * sigma * sigma));
}
