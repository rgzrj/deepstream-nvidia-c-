# ROS2 + IMU/陀螺仪 + 全局路径规划学习与实现思路

本文档用于思考：如果未来要在当前 Jetson 视觉项目基础上，引入 ROS2，并搭配 IMU/陀螺仪，实现机器人全局路径规划，应该怎么设计、怎么学习、怎么一步步操作。

当前项目已经完成了：

```text
海康相机采集
  -> DeepStream 推理
  -> 自定义 parser 后处理
  -> OSD 遮蔽显示
  -> Jetson 端运行
```

如果进一步扩展到机器人导航，需要新增一条 ROS2 机器人系统链路：

```text
传感器
  -> ROS2 topic
  -> TF 坐标变换
  -> 里程计/IMU 融合定位
  -> 地图
  -> 全局路径规划
  -> 局部避障
  -> 速度控制指令
  -> 底盘运动
```

## 一、先明确一个关键事实

### 1. 陀螺仪不能单独完成全局路径规划

陀螺仪主要测量：

```text
angular_velocity
```

也就是角速度。

IMU 通常包含：

```text
gyroscope: 角速度
accelerometer: 加速度
magnetometer: 磁场方向，部分 IMU 有
```

IMU 可以帮助估计姿态，尤其是：

```text
roll
pitch
yaw
```

但全局路径规划需要的不只是姿态，还需要：

```text
机器人现在在哪里
地图长什么样
目标点在哪里
障碍物在哪里
机器人能不能走过去
```

因此，完整导航通常至少需要：

```text
IMU + 轮速里程计 + 地图 + 定位算法
```

更推荐：

```text
IMU + 轮速里程计 + 激光雷达/深度相机 + SLAM/Nav2
```

如果是室外场景，还可以考虑：

```text
IMU + GPS + 轮速里程计 + Nav2
```

### 2. IMU 在路径规划中的真正作用

IMU 不是直接规划路径的，它主要帮助：

1. 提供机器人姿态。
2. 提供角速度。
3. 减少短时间转向误差。
4. 改善里程计方向估计。
5. 在机器人打滑、急转弯时提高定位稳定性。
6. 与轮速里程计、视觉里程计、GPS 等数据融合。

在 ROS2 中，IMU 通常发布：

```text
/imu/data
/imu/data_raw
```

消息类型：

```text
sensor_msgs/msg/Imu
```

然后通过：

```text
robot_localization
```

与里程计融合，输出：

```text
/odometry/filtered
```

也就是更稳定的机器人位姿估计。

## 二、推荐总体架构

### 1. 标准 ROS2 导航架构

推荐使用 ROS2 Nav2 作为全局路径规划和局部路径控制框架。

整体架构：

```text
Camera / LiDAR / Depth Camera
        ↓
Obstacle data / Costmap

Wheel Encoder
        ↓
/wheel/odom

IMU / Gyroscope
        ↓
/imu/data

/wheel/odom + /imu/data
        ↓
robot_localization EKF
        ↓
/odometry/filtered

Map / SLAM
        ↓
/map

TF:
map -> odom -> base_link -> camera_link / imu_link

Nav2
  ├── map_server
  ├── planner_server
  ├── controller_server
  ├── behavior_server
  ├── bt_navigator
  └── costmap_2d

        ↓
/cmd_vel
        ↓
底盘控制器
```

### 2. 和当前视觉项目的关系

当前项目主要做：

```text
相机输入 + AI 模型推理 + 画面显示
```

ROS2 导航项目主要做：

```text
定位 + 建图 + 路径规划 + 控制
```

两者可以这样结合：

#### 方案 A: 先独立运行，后面再桥接

第一阶段不要立刻把 DeepStream 代码改成 ROS2 节点。先让：

```text
DeepStream 视觉程序
ROS2 Nav2 导航系统
```

分别跑通。

之后再做桥接：

```text
DeepStream 检测结果 -> ROS2 topic
```

例如发布：

```text
/vision/detections
/vision/target_pose
/vision/semantic_obstacles
```

优点：

1. 风险小。
2. 容易调试。
3. 不会一次性把系统复杂度拉满。

#### 方案 B: 把当前 main.cpp 改造成 ROS2 节点

将当前 `main.cpp` 改造成一个 ROS2 C++ 节点：

```text
deepstream_vision_node
```

它可以发布：

```text
/camera/image_raw
/vision/detections
/vision/annotated_image
```

也可以订阅：

```text
/nav/status
/robot/mode
```

优点：

1. 系统统一在 ROS2 里。
2. topic、rviz、rosbag 都能用。
3. 便于后续和导航、控制、任务决策结合。

缺点：

1. 工程复杂度更高。
2. CMake 依赖更多。
3. DeepStream、GStreamer、ROS2、相机 SDK 要一起链接。

建议：

```text
先做方案 A，再做方案 B。
```

## 三、推荐硬件组合

### 1. 最低可行方案

如果只是学习 ROS2 全局路径规划，最低可以：

```text
Jetson
两轮差速底盘
轮速编码器
IMU
2D 激光雷达 或 深度相机
```

不推荐只用：

```text
Jetson + IMU
```

因为只有 IMU 时，位置会严重漂移，无法稳定完成全局路径规划。

### 2. 电赛推荐方案

比较稳的比赛级方案：

```text
Jetson Orin / Xavier
STM32 或其他底盘控制器
轮速编码器
IMU
2D LiDAR 或深度相机
普通 RGB 相机或工业相机
ROS2 Nav2
```

职责分配：

| 模块 | 建议负责内容 |
| --- | --- |
| Jetson | ROS2、视觉、路径规划、AI 推理 |
| STM32 | 电机控制、编码器读取、底盘闭环 |
| IMU | 姿态、角速度、辅助定位 |
| LiDAR/Depth | 建图、避障、costmap |
| Camera | 目标识别、语义感知 |

## 四、ROS2 中的核心概念

### 1. Topic

ROS2 中不同模块通过 topic 通信。

常见 topic：

```text
/imu/data
/odom
/odometry/filtered
/scan
/map
/tf
/tf_static
/cmd_vel
/goal_pose
```

### 2. Message

常见消息类型：

```text
sensor_msgs/msg/Imu
sensor_msgs/msg/LaserScan
sensor_msgs/msg/Image
nav_msgs/msg/Odometry
nav_msgs/msg/OccupancyGrid
geometry_msgs/msg/Twist
geometry_msgs/msg/PoseStamped
vision_msgs/msg/Detection2DArray
```

### 3. TF 坐标树

导航系统依赖 TF。

推荐坐标树：

```text
map
  -> odom
      -> base_link
          -> imu_link
          -> camera_link
          -> laser_link
```

含义：

| 坐标系 | 含义 |
| --- | --- |
| `map` | 全局地图坐标系 |
| `odom` | 局部里程计坐标系 |
| `base_link` | 机器人底盘中心 |
| `imu_link` | IMU 坐标系 |
| `camera_link` | 相机坐标系 |
| `laser_link` | 雷达坐标系 |

最常见的问题：

1. TF 缺失。
2. 坐标轴方向错。
3. `base_link` 和传感器位置关系不对。
4. `map -> odom -> base_link` 链断了。

### 4. REP-103 坐标约定

ROS 机器人常用坐标约定：

```text
x: 前方
y: 左方
z: 上方
```

IMU 安装时要特别注意：

1. IMU 的 x 轴是否朝前。
2. y 轴是否朝左。
3. z 轴是否朝上。
4. yaw 正方向是否和 ROS 约定一致。

如果 IMU 方向装反，需要通过：

```text
static_transform_publisher
```

或驱动参数修正。

## 五、全局路径规划需要哪些模块

### 1. 地图

全局路径规划必须有地图。

常见地图来源：

```text
手工地图
SLAM 建图
已有地图文件
GPS 地图
```

室内常用：

```text
slam_toolbox
map_server
```

地图文件通常包括：

```text
map.pgm
map.yaml
```

### 2. 定位

机器人要知道自己在地图中的位置。

常见定位方式：

| 场景 | 定位方案 |
| --- | --- |
| 室内已知地图 + 雷达 | AMCL |
| 室内未知环境 | SLAM Toolbox |
| 室外 | GPS + IMU + odom |
| 视觉场景 | Visual SLAM / VIO |

### 3. 里程计

里程计可以来自：

```text
轮速编码器
视觉里程计
激光里程计
```

常见 topic：

```text
/odom
```

消息类型：

```text
nav_msgs/msg/Odometry
```

### 4. IMU 融合

推荐用：

```text
robot_localization
```

把：

```text
/odom
/imu/data
```

融合成：

```text
/odometry/filtered
```

### 5. Nav2

Nav2 是 ROS2 的导航框架。

核心功能：

1. 全局路径规划。
2. 局部路径跟踪。
3. 避障。
4. 目标点导航。
5. 恢复行为。
6. 行为树任务管理。

常用节点：

```text
map_server
amcl
planner_server
controller_server
behavior_server
bt_navigator
waypoint_follower
```

## 六、建议的软件包

如果 Jetson 是 Ubuntu 22.04，推荐 ROS2 Humble。

如果 Jetson 是 Ubuntu 24.04，推荐 ROS2 Jazzy。

以下命令以 Humble 为例：

```bash
sudo apt update
sudo apt install \
  ros-humble-navigation2 \
  ros-humble-nav2-bringup \
  ros-humble-robot-localization \
  ros-humble-slam-toolbox \
  ros-humble-tf-transformations \
  ros-humble-imu-filter-madgwick \
  ros-humble-vision-msgs
```

如果某个包不存在，先用：

```bash
apt search ros-humble-包名
```

确认实际名称。

## 七、推荐 ROS2 工作空间结构

建议新建一个 ROS2 工作空间：

```text
~/ros2_ws/
├── src/
│   ├── robot_bringup/
│   ├── imu_driver/
│   ├── base_controller/
│   ├── vision_bridge/
│   └── nav2_config/
└── install/
```

各包职责：

| 包名 | 职责 |
| --- | --- |
| `robot_bringup` | 总启动入口 |
| `imu_driver` | 读取 IMU/陀螺仪数据 |
| `base_controller` | 与 STM32 通信，发布 odom，订阅 cmd_vel |
| `vision_bridge` | 当前 DeepStream 项目和 ROS2 的桥 |
| `nav2_config` | Nav2 参数、地图、launch 文件 |

## 八、第一阶段：先跑通 ROS2 基础

### 1. 创建工作空间

```bash
mkdir -p ~/ros2_ws/src
cd ~/ros2_ws
colcon build
source install/setup.bash
```

建议加入 `.bashrc`：

```bash
echo "source /opt/ros/humble/setup.bash" >> ~/.bashrc
echo "source ~/ros2_ws/install/setup.bash" >> ~/.bashrc
```

### 2. 检查 ROS2 是否正常

终端 1：

```bash
ros2 run demo_nodes_cpp talker
```

终端 2：

```bash
ros2 run demo_nodes_py listener
```

如果能看到消息，说明 ROS2 基础环境正常。

### 3. 学会常用命令

```bash
ros2 topic list
ros2 topic echo /topic_name
ros2 topic hz /topic_name
ros2 node list
ros2 node info /node_name
ros2 interface show sensor_msgs/msg/Imu
ros2 run rqt_graph rqt_graph
rviz2
```

这些命令是 ROS2 排障的基本功。

## 九、第二阶段：接入 IMU/陀螺仪

### 1. IMU 应发布的数据

理想情况下，IMU 节点发布：

```text
/imu/data
```

消息类型：

```text
sensor_msgs/msg/Imu
```

内容包括：

```text
orientation
angular_velocity
linear_acceleration
covariance
```

如果 IMU 只有陀螺仪，没有姿态解算，可以先发布：

```text
angular_velocity
```

但这只能作为辅助数据，不能长期积分成稳定 yaw。

### 2. 检查 IMU 数据

```bash
ros2 topic list | grep imu
ros2 topic echo /imu/data
ros2 topic hz /imu/data
```

观察：

1. 频率是否稳定。
2. 静止时角速度是否接近 0。
3. 转动机器人时 z 轴角速度方向是否正确。
4. frame_id 是否为 `imu_link`。

### 3. IMU 安装方向检查

让机器人原地逆时针旋转。

正常情况下：

```text
angular_velocity.z > 0
```

如果方向相反，说明 IMU 坐标方向需要修正。

### 4. IMU 静态 TF

假设 IMU 安装在 `base_link` 上方，位置为：

```text
x = 0.0
y = 0.0
z = 0.08
```

可以发布静态 TF：

```bash
ros2 run tf2_ros static_transform_publisher \
  0 0 0.08 0 0 0 base_link imu_link
```

如果 IMU 安装方向不是标准方向，需要修改 roll/pitch/yaw。

## 十、第三阶段：底盘里程计

全局路径规划必须有机器人位移估计。

对于差速小车，底盘控制器需要发布：

```text
/odom
```

消息类型：

```text
nav_msgs/msg/Odometry
```

同时发布 TF：

```text
odom -> base_link
```

### 1. 轮速里程计基本公式

差速小车：

```text
v_left
v_right
wheel_base
```

线速度：

```text
v = (v_right + v_left) / 2
```

角速度：

```text
w = (v_right - v_left) / wheel_base
```

位姿积分：

```text
x += v * cos(theta) * dt
y += v * sin(theta) * dt
theta += w * dt
```

### 2. 为什么要融合 IMU

纯轮速里程计会因为：

1. 打滑。
2. 地面不平。
3. 轮径误差。
4. 编码器噪声。

导致方向漂移。

IMU 的角速度可以辅助修正 yaw，使转向更稳。

## 十一、第四阶段：robot_localization 融合

推荐使用：

```text
robot_localization
```

输入：

```text
/odom
/imu/data
```

输出：

```text
/odometry/filtered
```

示例 `ekf.yaml`：

```yaml
ekf_filter_node:
  ros__parameters:
    frequency: 50.0
    two_d_mode: true
    publish_tf: true

    map_frame: map
    odom_frame: odom
    base_link_frame: base_link
    world_frame: odom

    odom0: /odom
    odom0_config: [
      true,  true,  false,
      false, false, true,
      true,  false, false,
      false, false, true,
      false, false, false
    ]

    imu0: /imu/data
    imu0_config: [
      false, false, false,
      false, false, true,
      false, false, false,
      false, false, true,
      true,  false, false
    ]
    imu0_remove_gravitational_acceleration: true
```

说明：

1. `two_d_mode: true` 表示只做平面机器人定位。
2. odom 提供 x、y、yaw、vx、wz。
3. IMU 提供 yaw、wz、部分加速度信息。
4. 如果 IMU yaw 不稳定，可以先只融合 `angular_velocity.z`。

启动：

```bash
ros2 run robot_localization ekf_node --ros-args --params-file ekf.yaml
```

检查：

```bash
ros2 topic echo /odometry/filtered
ros2 run tf2_ros tf2_echo odom base_link
```

## 十二、第五阶段：建图

如果没有地图，需要先建图。

推荐室内使用：

```text
slam_toolbox
```

输入：

```text
/scan
/tf
/odom 或 /odometry/filtered
```

输出：

```text
/map
```

常见命令：

```bash
ros2 launch slam_toolbox online_async_launch.py
```

打开 RViz：

```bash
rviz2
```

保存地图：

```bash
ros2 run nav2_map_server map_saver_cli -f ~/maps/my_map
```

得到：

```text
my_map.yaml
my_map.pgm
```

## 十三、第六阶段：Nav2 全局路径规划

Nav2 需要：

```text
地图
定位
TF
传感器障碍物数据
机器人尺寸
速度限制
```

### 1. Nav2 输入输出

输入：

```text
/map
/tf
/scan
/odometry/filtered
/goal_pose
```

输出：

```text
/cmd_vel
```

### 2. 关键配置项

#### global_costmap

负责全局地图代价。

包括：

1. 静态地图。
2. 障碍物。
3. 膨胀层。

#### local_costmap

负责机器人附近实时避障。

包括：

1. 雷达/深度相机障碍物。
2. 膨胀层。
3. 局部窗口。

#### planner_server

负责全局路径规划。

常见 planner：

```text
NavFn
SmacPlanner2D
ThetaStar
```

#### controller_server

负责沿路径运动。

常见 controller：

```text
DWB
Regulated Pure Pursuit
MPPI
```

### 3. 启动 Nav2

如果已有地图：

```bash
ros2 launch nav2_bringup bringup_launch.py \
  map:=/home/nvidia/maps/my_map.yaml \
  params_file:=/home/nvidia/ros2_ws/src/nav2_config/config/nav2_params.yaml
```

在 RViz 中：

1. 设置初始位姿。
2. 发送目标点。
3. 查看全局路径。
4. 查看局部路径。
5. 查看 costmap。

命令行发送目标点示例：

```bash
ros2 action send_goal /navigate_to_pose nav2_msgs/action/NavigateToPose "{
  pose: {
    header: {frame_id: 'map'},
    pose: {
      position: {x: 1.0, y: 0.5, z: 0.0},
      orientation: {w: 1.0}
    }
  }
}"
```

## 十四、如何把当前视觉项目接入 ROS2

### 方案 1：发布检测结果

当前 DeepStream 已经能检测人脸并遮蔽。

未来如果换成目标检测模型，可以在 `RedactionOsdSinkPadProbe()` 中把检测框发布成 ROS2 topic。

推荐消息：

```text
vision_msgs/msg/Detection2DArray
```

topic：

```text
/vision/detections
```

每个检测结果包含：

```text
class_id
score
bbox center
bbox size
```

用途：

1. 目标识别。
2. 任务触发。
3. 语义避障。
4. 目标点生成。

### 方案 2：发布目标点

如果视觉模型识别到某个目标，比如：

```text
目标物
标志牌
数字
颜色块
```

可以根据目标位置生成导航目标：

```text
/goal_pose
```

消息类型：

```text
geometry_msgs/msg/PoseStamped
```

然后交给 Nav2 导航。

### 方案 3：把视觉结果加入 costmap

如果视觉模型检测到障碍物，可以把它转成 costmap 障碍物。

实现方式：

1. 将 2D bbox 结合深度估计成 3D 点。
2. 发布 `PointCloud2`。
3. 让 Nav2 local costmap 订阅该点云。

或：

1. 写自定义 costmap layer。
2. 直接把语义障碍物写入 costmap。

这个方案更高级，但比赛中很有价值。

## 十五、推荐实现步骤

### Step 1: ROS2 环境跑通

目标：

```text
能运行 talker/listener
能看到 topic
能打开 rviz2
```

完成标志：

```bash
ros2 topic list
```

能正常输出。

### Step 2: IMU 节点跑通

目标：

```text
/imu/data 正常发布
```

检查：

```bash
ros2 topic echo /imu/data
ros2 topic hz /imu/data
```

完成标志：

1. 静止时角速度接近 0。
2. 转动时 z 轴角速度方向正确。
3. frame_id 正确。

### Step 3: 底盘里程计跑通

目标：

```text
/odom 正常发布
odom -> base_link TF 正常
```

检查：

```bash
ros2 topic echo /odom
ros2 run tf2_ros tf2_echo odom base_link
```

完成标志：

1. 推动车或控制车运动时，x/y/yaw 变化合理。
2. 原地转向时 yaw 变化合理。
3. TF 不报错。

### Step 4: EKF 融合跑通

目标：

```text
/odometry/filtered 正常发布
```

检查：

```bash
ros2 topic echo /odometry/filtered
ros2 run tf2_ros tf2_echo odom base_link
```

完成标志：

1. 数据稳定。
2. 机器人转向时 yaw 更平滑。
3. 不出现 TF 冲突。

### Step 5: 建图跑通

目标：

```text
slam_toolbox 能生成地图
```

检查：

```bash
rviz2
```

完成标志：

1. RViz 能看到 `/map`。
2. 机器人移动时地图逐渐生成。
3. 能保存 `map.yaml` 和 `map.pgm`。

### Step 6: Nav2 跑通

目标：

```text
能在 RViz 中发送目标点，机器人规划路径并运动
```

完成标志：

1. RViz 能显示 global path。
2. RViz 能显示 local path。
3. `/cmd_vel` 有输出。
4. 机器人能朝目标运动。

### Step 7: 视觉项目接入

目标：

```text
DeepStream 检测结果发布为 ROS2 topic
```

完成标志：

```bash
ros2 topic echo /vision/detections
```

能看到检测结果。

## 十六、常见问题和排查

### 1. Nav2 不规划路径

检查：

```bash
ros2 topic echo /map
ros2 topic echo /goal_pose
ros2 run tf2_ros tf2_echo map base_link
```

常见原因：

1. 没有地图。
2. 没有定位。
3. TF 不完整。
4. 起点或终点在障碍物里。
5. costmap 参数错误。

### 2. 机器人路径规划正常，但不动

检查：

```bash
ros2 topic echo /cmd_vel
```

如果 `/cmd_vel` 有数据，但车不动：

1. 底盘控制器没有订阅 `/cmd_vel`。
2. 串口通信失败。
3. 电机驱动未使能。
4. 速度单位或方向错。

如果 `/cmd_vel` 没数据：

1. controller_server 没启动。
2. Nav2 lifecycle 节点未激活。
3. costmap 报错。
4. TF 报错。

### 3. 机器人定位漂移

可能原因：

1. 轮径参数不准。
2. 轮距参数不准。
3. IMU 有零偏。
4. 地面打滑。
5. EKF 配置不合理。
6. IMU 坐标轴方向错。

排查：

```bash
ros2 topic echo /imu/data
ros2 topic echo /odom
ros2 topic echo /odometry/filtered
```

### 4. RViz 中 TF 报错

检查：

```bash
ros2 run tf2_tools view_frames
ros2 run tf2_ros tf2_echo map base_link
ros2 run tf2_ros tf2_echo odom base_link
```

常见问题：

1. 缺 `map -> odom`。
2. 缺 `odom -> base_link`。
3. 缺 `base_link -> imu_link`。
4. frame_id 名字不统一。
5. 时间戳不同步。

### 5. IMU 数据看起来乱

检查：

1. 波特率是否正确。
2. 驱动解析协议是否正确。
3. 坐标轴是否符合 ROS 约定。
4. 静止时角速度是否接近 0。
5. 是否受到电机磁场干扰。

注意：

如果 IMU 使用磁力计估计 yaw，电机、电源线、铁磁材料会严重干扰磁场。

## 十七、学习路线

### 阶段 1：ROS2 基础

学习内容：

1. node。
2. topic。
3. service。
4. action。
5. parameter。
6. launch。
7. colcon。

练习：

1. 写一个 publisher。
2. 写一个 subscriber。
3. 发布 `geometry_msgs/msg/Twist`。
4. 用 launch 同时启动多个节点。

### 阶段 2：机器人坐标系和 TF

学习内容：

1. `map`。
2. `odom`。
3. `base_link`。
4. `imu_link`。
5. `camera_link`。
6. `tf_static`。

练习：

1. 发布 `base_link -> imu_link`。
2. 发布 `base_link -> camera_link`。
3. 用 RViz 查看 TF。
4. 用 `tf2_echo` 检查变换。

### 阶段 3：IMU 和里程计

学习内容：

1. `sensor_msgs/msg/Imu`。
2. `nav_msgs/msg/Odometry`。
3. 轮速里程计。
4. IMU 零偏。
5. yaw 漂移。

练习：

1. 读取 IMU。
2. 观察静止零偏。
3. 原地旋转检查 yaw。
4. 写简单差速 odom。

### 阶段 4：robot_localization

学习内容：

1. EKF。
2. 传感器融合。
3. covariance。
4. `two_d_mode`。
5. `odom_frame`、`base_link_frame`、`world_frame`。

练习：

1. 融合 `/odom` 和 `/imu/data`。
2. 输出 `/odometry/filtered`。
3. 在 RViz 中观察轨迹。

### 阶段 5：SLAM 建图

学习内容：

1. occupancy grid。
2. 激光雷达 `/scan`。
3. SLAM Toolbox。
4. 地图保存。

练习：

1. 用雷达建图。
2. 保存地图。
3. 重新加载地图。

### 阶段 6：Nav2

学习内容：

1. global planner。
2. local planner。
3. costmap。
4. inflation layer。
5. behavior tree。
6. lifecycle node。

练习：

1. 在 RViz 中设定目标点。
2. 查看全局路径。
3. 查看局部路径。
4. 调整机器人半径。
5. 调整速度限制。

### 阶段 7：视觉和导航结合

学习内容：

1. `vision_msgs`。
2. 目标检测结果发布。
3. 视觉目标点生成。
4. 语义 costmap。
5. AI 任务决策。

练习：

1. 把 DeepStream 检测结果发成 ROS2 topic。
2. 在 RViz 中显示检测框。
3. 根据检测结果触发导航目标。
4. 将视觉障碍物加入局部 costmap。

## 十八、针对电赛的建议路线

如果目标是未来打电赛，不建议一上来就做完整大系统。

推荐顺序：

### 第 1 周：ROS2 基础和 TF

目标：

```text
会创建包
会写节点
会发布 topic
会看 TF
```

### 第 2 周：IMU 和底盘

目标：

```text
IMU 数据稳定
底盘能接收 /cmd_vel
能发布 /odom
```

### 第 3 周：EKF 融合

目标：

```text
/odom + /imu/data -> /odometry/filtered
```

### 第 4 周：建图

目标：

```text
用 slam_toolbox 建出一张可用地图
```

### 第 5 周：Nav2 导航

目标：

```text
RViz 发送目标点，机器人能规划并移动
```

### 第 6 周：视觉接入

目标：

```text
DeepStream 检测结果 -> ROS2 topic
视觉结果能影响导航或任务决策
```

## 十九、和当前项目最直接的结合点

当前项目可以保留的部分：

```text
main.cpp 中的相机采集
DeepStream pipeline
nvdsinfer_custom_fd_lpd.cpp
build_engine.sh
configs/pgie_config_fd_lpd.txt
```

未来要新增的部分：

```text
ROS2 节点初始化 rclcpp
检测结果 publisher
IMU driver
底盘 odom publisher
cmd_vel subscriber
robot_localization config
Nav2 config
TF launch
```

建议新增目录：

```text
ros2_nav_notes/
├── config/
│   ├── ekf.yaml
│   ├── nav2_params.yaml
│   └── robot_frames.yaml
├── launch/
│   ├── bringup.launch.py
│   ├── localization.launch.py
│   └── navigation.launch.py
└── src/
    ├── imu_driver/
    ├── base_controller/
    └── vision_bridge/
```

## 二十、最终结论

如果要通过 ROS2 搭配陀螺仪实现全局路径规划，正确思路不是：

```text
陀螺仪 -> 直接规划路径
```

而是：

```text
IMU/陀螺仪
  + 轮速里程计
  + 地图
  + 定位
  + Nav2
  -> 全局路径规划
```

IMU 是定位稳定性的辅助传感器，不是全局规划的全部。

当前视觉项目可以作为未来 ROS2 系统中的视觉感知模块。真正完整的电赛机器人系统应该逐步扩展为：

```text
视觉 AI 感知
  + IMU 姿态
  + 轮速里程计
  + SLAM/地图
  + Nav2 路径规划
  + 底盘控制
```

这条路线学下来，会覆盖电赛中非常核心的能力：

1. ROS2 工程能力。
2. Jetson 部署能力。
3. 传感器融合能力。
4. 实时视觉能力。
5. 路径规划能力。
6. 嵌入式控制协同能力。

这比单独跑一个模型更接近真正的机器人系统。
