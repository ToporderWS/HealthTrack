-- ============================================================================
-- 《康迹 HealthTrack》开发数据库初始化脚本
-- ============================================================================
-- 用途：创建本机**开发库**与**开发账号**（需用 MySQL 管理员账号执行一次）
-- 依据：
--   * S1-B 数据库设计文档 v1.2（字符集 / 排序规则 / 8 张表由 Alembic 建立）
--   * S1-D《开发环境与工程实施准备》§7.1（**仅建立开发环境数据库**，不建生产库）
--
-- 执行方式（Windows，管理员 MySQL 账号）：
--   "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe" -u root -p < scripts\init_db_dev.sql
--
-- ⚠️ 请先把下面的 CHANGE_ME_DEV_PASSWORD 替换为**你自定的开发账号密码**，
--    并把同一账号密码填入 backend/.env.development 的 MYSQL_USER / MYSQL_PASSWORD。
-- ⚠️ 本文件**不得**写入真实密码后提交到 Git（若填写了真实密码，请勿提交）。
-- ============================================================================

-- 1) 创建开发库（字符集与排序规则按 S1-B 冻结：utf8mb4 / utf8mb4_0900_ai_ci）
CREATE DATABASE IF NOT EXISTS `kangji_healthtrack`
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_0900_ai_ci;

-- 2) 创建专用开发账号（避免应用直接使用 root）
--    说明：S1-D §4.3 建议业务账号最小权限（仅 DML）、DDL 由迁移账号执行；
--    开发阶段为便于 Alembic 执行迁移，此处暂授予该库全部权限。
--    生产环境必须拆分账号权限（属后续批次，V1.0 不上架）。
CREATE USER IF NOT EXISTS 'kangji_dev'@'localhost' IDENTIFIED BY 'CHANGE_ME_DEV_PASSWORD';
GRANT ALL PRIVILEGES ON `kangji_healthtrack`.* TO 'kangji_dev'@'localhost';
FLUSH PRIVILEGES;

-- 3) 核验（应输出 kangji_healthtrack）
SHOW DATABASES LIKE 'kangji_healthtrack';
