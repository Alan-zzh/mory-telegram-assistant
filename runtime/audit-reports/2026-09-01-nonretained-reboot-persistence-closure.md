# 非保留项目开机复活入口清理回执

时间：2026-09-01 01:23–01:36 CST
范围：共享生产主机；仅保留 Mory、MoryFansBot、MediaOps-COO 及必要系统服务。

## 结论

- PM2 保存态只含 MoryFansBot 两进程和 MediaOps-COO 三进程；没有非保留项目。
- Docker、containerd、Nginx、sing-box 及非保留项目服务均未运行，相关 unit/timer 为 disabled、masked、inactive 或 not-found。
- root cron 仅保留 Mory 两分钟 watchdog；ubuntu cron 仅保留 MediaOps 五分钟 watchdog；用户级 systemd wants 为空。
- 找到并移除一项真实资源残留：`/swap-tokenlab-4g.img` 为 TokenLab 专用、开机自动启用的 4 GiB 交换文件。

## 受控变更

1. 确认目标为 root:root、0600、4,294,967,296 字节的普通文件，`/etc/fstab` 精确命中一行。
2. 确认主交换文件 `/swap.img` 正常，主机可用内存大于 6 GiB，TokenLab 交换区仅使用约 19 MiB。
3. 将 fstab、交换状态、文件属性、根盘状态和恢复命令保存到 root-only 备份：
   `/root/service-stop-backups/20260901-013151-tokenlab-swap`。
4. 执行精确 `swapoff`，原子删除 fstab 对应行，daemon-reload 后删除目标文件；未重启主机。

## 验证

- 目标文件：不存在；fstab 命中：0；活动交换区仅剩 `/swap.img`。
- 实际释放：4,294,979,584 字节；根盘可用空间由 49,335,726,080 增至 53,630,492,672 字节，占用由 60% 降至 56%。
- Mory Bot、Dashboard、MediaOps API、两套 PM2 开机服务均 active/enabled。
- Mory Bot 与 Dashboard `NRestarts=0`；生产只读巡检 17 pass / 0 gap / 0 failed。
- MoryFansBot 两进程和 MediaOps-COO 三进程 online；非保留项目进程与运行中 Docker 容器均为 0。
- TokenPass 残留计时器为 inactive/not-found；其他非保留计时器为 inactive 且 disabled/masked，不会按重启恢复。

## 恢复边界

该交换文件不含项目数据，未复制 4 GiB 本体；root-only 备份内保存了可核验的 fstab 原文、SHA-256 和确定性重建命令。需要恢复 TokenLab 时，须由老板重新明确授权后按回执重建，不自动恢复。
