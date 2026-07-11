import type { CourseQuestion } from "../types.js";

export const matchingQuestions: CourseQuestion[] = [
  {
    id: "mq1",
    prompt: "哪个动物喜欢吃胡萝卜？",
    target: "胡萝卜",
    options: [
      { id: "rabbit", label: "兔子" },
      { id: "cat", label: "小猫" },
      { id: "dog", label: "小狗" }
    ],
    correctOptionId: "rabbit",
    hint: "想一想，长耳朵的动物最喜欢胡萝卜。",
    errorTypeOnWrong: "mismatch"
  },
  {
    id: "mq2",
    prompt: "哪个天气会用到雨伞？",
    target: "雨伞",
    options: [
      { id: "rainy", label: "下雨天" },
      { id: "sunny", label: "晴天" },
      { id: "snowy", label: "下雪天" }
    ],
    correctOptionId: "rainy",
    hint: "看看哪里会落下雨滴。",
    errorTypeOnWrong: "mismatch"
  },
  {
    id: "mq3",
    prompt: "哪个交通工具在天上飞？",
    target: "天空",
    options: [
      { id: "train", label: "火车" },
      { id: "plane", label: "飞机" },
      { id: "bicycle", label: "自行车" }
    ],
    correctOptionId: "plane",
    hint: "它有翅膀，会飞得很高。",
    errorTypeOnWrong: "mismatch"
  },
  {
    id: "mq4",
    prompt: "哪个季节会下雪？",
    target: "雪花",
    options: [
      { id: "spring", label: "春天" },
      { id: "summer", label: "夏天" },
      { id: "winter", label: "冬天" }
    ],
    correctOptionId: "winter",
    hint: "最冷的季节会看到雪。",
    errorTypeOnWrong: "mismatch"
  }
];
