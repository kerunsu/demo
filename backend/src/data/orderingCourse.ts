import type { CourseQuestion } from "../types.js";

export const orderingQuestions: CourseQuestion[] = [
  {
    id: "oq1",
    prompt: "按从小到大，应该选哪个数字？",
    target: "规则：从小到大",
    options: [
      { id: "num2", label: "2" },
      { id: "num9", label: "9" }
    ],
    correctOptionId: "num2",
    hint: "从更小的数字开始。",
    errorTypeOnWrong: "wrong_order"
  },
  {
    id: "oq2",
    prompt: "按从高到低，先选哪座山？",
    target: "规则：从高到低",
    options: [
      { id: "mountainA", label: "高山" },
      { id: "mountainB", label: "小山" }
    ],
    correctOptionId: "mountainA",
    hint: "先选更高的那个。",
    errorTypeOnWrong: "wrong_order"
  },
  {
    id: "oq3",
    prompt: "按从短到长，先选哪条线？",
    target: "规则：从短到长",
    options: [
      { id: "lineShort", label: "短线" },
      { id: "lineLong", label: "长线" }
    ],
    correctOptionId: "lineShort",
    hint: "先找最短的线。",
    errorTypeOnWrong: "wrong_order"
  },
  {
    id: "oq4",
    prompt: "按从多到少，先选哪一组？",
    target: "规则：从多到少",
    options: [
      { id: "manyDots", label: "●●●●●" },
      { id: "fewDots", label: "●●" }
    ],
    correctOptionId: "manyDots",
    hint: "先选数量更多的一组。",
    errorTypeOnWrong: "wrong_order"
  }
];
