const NUWAY_DATA = {
  today: "2026-08-13",
  vehicles: [
    {
      id: "nuway-1", name: "nUWAy-1", operator: "K. Smith", passengers: 4,
      battery: 78, chargeState: "Discharging", autonomyMode: "Autonomous",
      lastSeenMinutes: 1,
      tech: { Network: "Online", GPS: "Healthy", LiDAR: "Healthy", Cameras: "Healthy", "Autonomous Software": "Running" },
      trips: 12, completed: 11, autonomousHours: 6.2,
      availability: 93, utilisation: 76, autonomousUtilisation: 69
    },
    {
      id: "nuway-2", name: "nUWAy-2", operator: "T. Nguyen", passengers: 2,
      battery: 61, chargeState: "Discharging", autonomyMode: "Autonomous",
      lastSeenMinutes: 3,
      tech: { Network: "Online", GPS: "Healthy", LiDAR: "Healthy", Cameras: "Healthy", "Autonomous Software": "Running" },
      trips: 9, completed: 9, autonomousHours: 5.4,
      availability: 96, utilisation: 71, autonomousUtilisation: 66
    },
    {
      id: "nuway-3", name: "nUWAy-3", operator: "A. Lee", passengers: 0,
      battery: 44, chargeState: "Charging", autonomyMode: "Manual",
      lastSeenMinutes: 7,
      tech: { Network: "Online", GPS: "Healthy", LiDAR: "Healthy", Cameras: "Healthy", "Autonomous Software": "Running" },
      trips: 6, completed: 6, autonomousHours: 2.8,
      availability: 88, utilisation: 58, autonomousUtilisation: 51
    },
    {
      id: "nuway-4", name: "nUWAy-4", operator: "—", passengers: 0,
      battery: 23, chargeState: "Unknown", autonomyMode: "Unknown",
      lastSeenMinutes: 22,
      tech: { Network: "Offline", GPS: "Offline", LiDAR: "Offline", Cameras: "Offline", "Autonomous Software": "Offline" },
      trips: 3, completed: 2, autonomousHours: 1.1,
      availability: 61, utilisation: 32, autonomousUtilisation: 28
    }
  ],
  history: {
    "2026-08-13": {
      paths: {
        "nuway-1": [[-31.98198,115.81864],[-31.98143,115.81922],[-31.98084,115.82010],[-31.98030,115.82100],[-31.97986,115.82188],[-31.97945,115.82272]],
        "nuway-2": [[-31.98405,115.81763],[-31.98355,115.81838],[-31.98302,115.81920],[-31.98242,115.82005],[-31.98188,115.82082]],
        "nuway-3": [[-31.97905,115.81710],[-31.97872,115.81805],[-31.97848,115.81907],[-31.97828,115.82016]],
        "nuway-4": [[-31.98475,115.82130],[-31.98418,115.82182],[-31.98370,115.82225]]
      },
      events: [
        { vehicle:"nuway-1", type:"disengagement", time:"09:18:22", lat:-31.98065, lng:115.82042, reason:"Manual operator intervention" },
        { vehicle:"nuway-1", type:"reengagement", time:"09:19:11", lat:-31.98049, lng:115.82070, reason:"Autonomous mode resumed" },
        { vehicle:"nuway-2", type:"disengagement", time:"09:42:37", lat:-31.98268, lng:115.81966, reason:"Obstacle avoidance review" },
        { vehicle:"nuway-2", type:"reengagement", time:"09:44:03", lat:-31.98242, lng:115.82005, reason:"Autonomous mode resumed" },
        { vehicle:"nuway-3", type:"disengagement", time:"08:51:18", lat:-31.97852, lng:115.81890, reason:"Manual control requested" },
        { vehicle:"nuway-3", type:"reengagement", time:"08:53:02", lat:-31.97844, lng:115.81934, reason:"Autonomous mode resumed" }
      ]
    },
    "2026-08-12": {
      paths: {
        "nuway-1": [[-31.98220,115.81795],[-31.98160,115.81882],[-31.98108,115.81964],[-31.98057,115.82044],[-31.98003,115.82131]],
        "nuway-2": [[-31.98388,115.82162],[-31.98325,115.82110],[-31.98267,115.82055],[-31.98206,115.81992]],
        "nuway-3": [[-31.97937,115.82210],[-31.97918,115.82110],[-31.97902,115.82012],[-31.97886,115.81916]]
      },
      events: [
        { vehicle:"nuway-1", type:"disengagement", time:"14:12:48", lat:-31.98108, lng:115.81964, reason:"Operator intervention" },
        { vehicle:"nuway-1", type:"reengagement", time:"14:14:06", lat:-31.98091, lng:115.81992, reason:"Autonomous mode resumed" }
      ]
    },
    "2026-08-11": {
      paths: {
        "nuway-1": [[-31.97890,115.81810],[-31.97934,115.81888],[-31.97981,115.81973],[-31.98028,115.82056]],
        "nuway-2": [[-31.98396,115.81804],[-31.98332,115.81881],[-31.98278,115.81955],[-31.98225,115.82029]]
      },
      events: [
        { vehicle:"nuway-2", type:"disengagement", time:"10:03:51", lat:-31.98278, lng:115.81955, reason:"Pedestrian proximity" },
        { vehicle:"nuway-2", type:"reengagement", time:"10:05:10", lat:-31.98255, lng:115.81987, reason:"Autonomous mode resumed" }
      ]
    }
  },
  timeUsage: {
    all: { Autonomous:58, Manual:9, Idle:14, Charging:8, Downtime:6, Unscheduled:5 },
    "nuway-1": { Autonomous:63, Manual:7, Idle:13, Charging:8, Downtime:5, Unscheduled:4 },
    "nuway-2": { Autonomous:60, Manual:8, Idle:16, Charging:7, Downtime:5, Unscheduled:4 },
    "nuway-3": { Autonomous:44, Manual:14, Idle:20, Charging:12, Downtime:6, Unscheduled:4 },
    "nuway-4": { Autonomous:23, Manual:9, Idle:21, Charging:15, Downtime:24, Unscheduled:8 }
  }
};
