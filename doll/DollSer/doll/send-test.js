const { Client } = require('node-osc');

const HOST = process.env.DOLL_OSC_HOST || '127.0.0.1';
const PORT = Number(process.env.DOLL_OSC_PORT || 12000);
const NEUTRAL_POSE = { pitch: 180, yaw: 180, arml: 270, armr: 270 };

function usage() {
  console.log('Usage:');
  console.log('  node send-test.js neutral [time]');
  console.log('  node send-test.js axis <pitch|yaw|arml|armr> <value> [time]');
  console.log('  node send-test.js pose <pitch> <yaw> <arml> <armr> [time]');
  console.log('');
  console.log('Examples:');
  console.log('  node send-test.js neutral 500');
  console.log('  node send-test.js axis yaw 185 500');
  console.log('  node send-test.js pose 180 175 270 270 500');
}

function clampAngle(value) {
  return Math.min(359, Math.max(0, Math.round(Number(value))));
}

function clampTime(value) {
  return Math.min(5000, Math.max(50, Math.round(Number(value))));
}

function sendPose(client, pose, time) {
  const messages = [
    ['/pitch', pose.pitch],
    ['/yaw', pose.yaw],
    ['/arml', pose.arml],
    ['/armr', pose.armr],
  ];

  messages.forEach(([address, value]) => {
    client.send(address, clampAngle(value), time);
  });
}

function main() {
  const [mode, ...args] = process.argv.slice(2);
  if (!mode) {
    usage();
    process.exit(1);
  }

  const client = new Client(HOST, PORT);
  let pose;
  let time = 500;

  if (mode === 'neutral') {
    time = clampTime(args[0] ?? 500);
    pose = { ...NEUTRAL_POSE };
  } else if (mode === 'axis') {
    const [axis, value, rawTime] = args;
    if (!['pitch', 'yaw', 'arml', 'armr'].includes(axis) || value === undefined) {
      usage();
      process.exit(1);
    }

    time = clampTime(rawTime ?? 500);
    pose = { ...NEUTRAL_POSE };
    pose[axis] = clampAngle(value);
  } else if (mode === 'pose') {
    const [pitch, yaw, arml, armr, rawTime] = args;
    if ([pitch, yaw, arml, armr].some((value) => value === undefined)) {
      usage();
      process.exit(1);
    }

    time = clampTime(rawTime ?? 500);
    pose = {
      pitch: clampAngle(pitch),
      yaw: clampAngle(yaw),
      arml: clampAngle(arml),
      armr: clampAngle(armr),
    };
  } else {
    usage();
    process.exit(1);
  }

  console.log(`Sending to ${HOST}:${PORT}`);
  console.log(`Pitch=${pose.pitch} Yaw=${pose.yaw} ArmL=${pose.arml} ArmR=${pose.armr} Time=${time}`);

  sendPose(client, pose, time);

  setTimeout(() => {
    client.close();
    process.exit(0);
  }, 100);
}

main();
