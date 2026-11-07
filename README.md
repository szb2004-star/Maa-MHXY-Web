<!-- markdownlint-disable MD033 MD041 -->
<p align="center">
  <img alt="LOGO" src="./docs/img/logo.png" width="220" />
</p>

<div align="center">

# MAA_MHXY_MG

![GitHub stars](https://img.shields.io/github/stars/gitlihang/Maa_MHXY_MG?style=flat-square)
![GitHub release](https://img.shields.io/github/v/release/gitlihang/Maa_MHXY_MG?style=flat-square)
![License](https://img.shields.io/github/license/gitlihang/Maa_MHXY_MG?style=flat-square)

基于 MaaFramework 的“梦手”自动化助手，结合图像识别与模拟控制，帮助完成高频日常与部分周常任务。

</div>

## 目录
- [项目简介](#项目简介)
- [功能列表](#功能列表)
- [教程文档](#教程文档) 
- [鸣谢](#鸣谢)
- [免责声明](#免责声明)
- [沟通交流](#沟通交流)
- [赞助](#赞助)

## 项目简介

`MAA_MHXY_MG` 是一个面向“梦手”的项目，依托 [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 实现。



> <b>重点说明：由于 69 级以下账号操作逻辑不同，部分功能对低等级小号的适配仍存在兼容性不足。</b>


## 功能列表

已完成的代表性功能包括：
- 签到、师门、秘境等日常任务
- 周长任务中的多项内容

完整功能明细请查看：[功能列表](./docs/功能列表.md)

## Web 中控版本
整个ui 是codex和harness 写的，本人不懂代码，但是觉得脚本的ui 还是要方便，改善了连接方式和可以局域网简单控制，如果实在有远程的需求也可以自行开放权限到公网，做不时之需，但是不安全。
新增同机多模拟器 Web 中控：设备扫描、命名任务组合、实例下拉选择配置、批量启停、日志、截图、实时监控和活动日志回放。任务库按个人日常、组队日常、周常、日常功能、养成服务分为两级目录；可跨分类组合保存，同一配置供多个实例复用。macOS 可直接导入 MuMu，Windows 可直接导入 MuMu / 雷电多开器中的现有实例（含未启动实例），实例右上角开关控制模拟器开关机，开机后等待 Android 就绪并自动打开游戏，下方「启动配置」执行所选组合。界面统一官方客户端，任务执行中显示右侧任务栏识别的文字和数字进度；账号中心可采集当前运行角色资料。

Windows：先运行 `setup-web.bat`，再运行 `start-web.bat`；浏览器打开 <http://127.0.0.1:8000>，直接进入控制台；同一局域网可免令牌访问本机 IP 的 8000 端口。需要 Python 3.10+。

完整安装、局域网访问和验证说明：[Web 中控使用说明](./docs/Web中控使用说明.md)。

## 教程文档

- [窗口运行教程](./docs/窗口运行教程.md)
- [CMD 运行教程](./docs/CMD运行教程.md)
- [功能列表](./docs/功能列表.md)

## 鸣谢

本项目由 [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 提供强力支持，感谢所有参与和支持项目开发的贡献者！

- [MaaFramework](https://github.com/MaaXYZ/MaaFramework)
- [MFAAvalonia](https://github.com/MaaXYZ/MFAAvalonia)
- [MXU](https://github.com/MistEO/MXU)


## 免责声明

本项目仅供学习与交流参考。

## 沟通交流

- QQ 群：`953819042`

## 赞助

<a href="https://afdian.com/a/gitlihang">
  <img width="200" src="https://pic1.afdiancdn.com/static/img/welcome/button-sponsorme.png">
</a>


### 自动登录与监控中心

实例开机后会等待 Android 就绪、打开官服游戏，并点击“登录游戏”，连续确认主界面后才提示完成。沿用游戏中已有的账号、服务器和角色；验证码、账号验证或登录超时会明确报错，需要在模拟器中处理。启动配置同样先检查登录。

“账号中心”下方的“监控中心”可在局域网查看多实例实时画面，支持单独观看/暂停、观看已开机实例、全部暂停和点击放大。采用 MJPEG，单路约 2 帧/秒、最长边 960 像素，同一实例多个观看者共享抓屏。切换页面、浏览器进入后台或最后一个观看者断开后停止采集；不含声音和远程点击。访问地址为 `http://运行电脑的局域网IP:8000/`，默认免令牌。

### 编组自动组队

在任务库「组队日常」选择「编组自动组队」，作为配置第一项。队长通过好友编组「自动组队」识别，只邀请编组内可邀请的联系人；其他实例自动接受左侧邀请弹窗。连续确认五名真人后，队长继续后续任务，队员持续跟队。支持等待时间、重复邀请、队长冲突检查及队长结束通知。详见 [组队说明](docs/description/web_auto_team.md)。

### 账号中心

按模拟器分切页保存角色资料与资产快照，支持单实例或已运行窗口采集，展示金币、银币、修炼及帮派技能等级和采集时间。采集与实例任务互斥，不自动打开关闭的模拟器；未显示或未识别的内容会明确标注。详情见 [Web 中控说明](docs/Web中控使用说明.md)。
