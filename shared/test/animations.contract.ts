import {
  MockRobotAnimationAdapter,
  ROBOT_ANIMATION_MANIFEST,
  type RobotAnimationAdapter,
  type RobotAnimationId,
  type RobotAnimationIntent,
  type RobotAnimationManifestItem
} from "../src/animations.js";

type Assert<T extends true> = T;
type Extends<TValue, TBase> = TValue extends TBase ? true : false;

type MockAdapterSatisfiesContract = Assert<Extends<MockRobotAnimationAdapter, RobotAnimationAdapter>>;
type EyeIsAnimationId = Assert<Extends<"eye", RobotAnimationId>>;
type IdleIsIntent = Assert<Extends<"idle", RobotAnimationIntent>>;

const firstManifestItem = ROBOT_ANIMATION_MANIFEST[0] satisfies RobotAnimationManifestItem;

void firstManifestItem;

