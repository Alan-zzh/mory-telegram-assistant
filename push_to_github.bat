@echo off
echo 将本地代码推送到GitHub仓库
echo.
echo 第一步：在GitHub上创建新仓库（手动）
echo 访问 https://github.com/new
echo 仓库名：mory-assistant（或自定义）
echo 不要初始化README、.gitignore或license
echo.
echo 第二步：设置远程仓库URL
set /p github_username=请输入你的GitHub用户名：
set /p repo_name=请输入仓库名（默认为mory-assistant）：
if "%repo_name%"=="" set repo_name=mory-assistant
git remote add origin https://github.com/%github_username%/%repo_name%.git
echo 已设置远程仓库：https://github.com/%github_username%/%repo_name%.git
echo.
echo 第三步：推送代码
git push -u origin main
echo.
echo 完成！仓库链接：https://github.com/%github_username%/%repo_name%
pause