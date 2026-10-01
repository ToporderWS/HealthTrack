-- ============================================================================
-- 《康迹 HealthTrack》**专用测试数据库**初始化脚本（B1-R-FIX · S1 / S7）
-- ============================================================================
-- 执行者：**由需求方本人用 MySQL 管理员账号（root / DBA）手动执行一次**。
-- 执行方式（Windows cmd / PowerShell，请用你自己的管理员账号）：
--     "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe" -u root -p < "C:\Users\Toporder-WS\Desktop\Demo\scripts\init_db_test.sql"
--   或：
--     "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe" -u root -p -e "SOURCE C:/Users/Toporder-WS/Desktop/Demo/scripts/init_db_test.sql"
--
-- ⚠️ 工程侧（Agent）**不会**执行本脚本，也**不会**尝试 root 登录，也不需要口令。
--
-- 目标实例（B1-R-FIX 只读实测）：
--     MySQL 8.0.33 @ 127.0.0.1:3306  (DESKTOP-3B04MQG)
--     datadir = C:\ProgramData\MySQL\MySQL Server 8.0\Data\
--     现有应用账号 = 'kangji_dev'@'localhost'
--       当前授权：GRANT USAGE ON *.*
--                 GRANT ALL PRIVILEGES ON `kangji_healthtrack`.*
--       实测：建/用测试库报 ERROR 1044 Access denied ⇒ 必须管理员执行本脚本。
--
-- ============================================================================
-- 本脚本的**边界承诺**（与需求方 10 条约束逐条对应）
-- ============================================================================
--  ✔ 只 CREATE 测试库 `kangji_healthtrack_test`
--  ✔ 只对 `kangji_healthtrack_test`.* 追加 kangji_dev 的权限
--  ✔ 不含任何 DROP DATABASE / DROP TABLE / TRUNCATE / DELETE / UPDATE / INSERT
--  ✔ 不触碰 `kangji_healthtrack` 的任何表或数据
--  ✔ 不改变 kangji_dev 对 `kangji_healthtrack` 的既有权限
--     （MySQL 的 GRANT 是**按库追加**的：对 A 库授权不会影响 B 库的既有授权）
--  ✔ 不含任何口令（仅引用**已存在**的账号，不 CREATE USER / 不 ALTER USER）
-- ============================================================================


-- ----------------------------------------------------------------------------
-- 【步骤 1】创建专用测试库
-- 用途：为 pytest 提供**物理隔离**的目标库（D0）。字符集 / 排序规则与开发库
--       实测值一致（utf8mb4 / utf8mb4_0900_ai_ci），与 S1-B 冻结口径一致。
-- 幂等：IF NOT EXISTS —— 若已存在则**不做任何改动**（不会覆盖、不会清空）。
-- ----------------------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS `kangji_healthtrack_test`
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_0900_ai_ci;


-- ----------------------------------------------------------------------------
-- 【步骤 2】把该库的权限授予现有应用账号
-- 用途：让 pytest / Alembic 能连上并建表（测试需要 DDL+DML）。
-- 作用域：**仅** `kangji_healthtrack_test`.* —— 明确写成 `库名.*`，
--         因此**不涉及** `kangji_healthtrack`，不改变该账号在开发库上的任何既有权限。
-- 说明：开发阶段沿用 scripts/init_db_dev.sql 的口径（ALL PRIVILEGES，便于 Alembic 迁移）；
--       生产环境必须拆分「迁移账号 / 业务账号」，属后续批次（V1.0 不上架）。
-- 备选（最小权限）：若你更倾向逐项授权，可把本行替换为
--   GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, ALTER, INDEX, REFERENCES,
--         CREATE TEMPORARY TABLES, LOCK TABLES, CREATE VIEW, SHOW VIEW, EXECUTE
--     ON `kangji_healthtrack_test`.* TO 'kangji_dev'@'localhost';
-- ----------------------------------------------------------------------------
GRANT ALL PRIVILEGES ON `kangji_healthtrack_test`.* TO 'kangji_dev'@'localhost';


-- ----------------------------------------------------------------------------
-- 【步骤 3】刷新权限缓存
-- 用途：使上面的 GRANT 立即生效（对 GRANT 语句本身非必需，但无害、
--       且能避免个别客户端会话缓存旧权限）。
-- 注意：FLUSH PRIVILEGES **不会**改变任何授权内容。
-- ----------------------------------------------------------------------------
FLUSH PRIVILEGES;


-- ============================================================================
-- 【只读验证】执行完上面 3 步后，请把下面整段再执行一遍，逐项核对期望值。
-- 本段**全部为 SELECT / SHOW**，不写任何数据。
-- ============================================================================

-- V1) 测试库已存在，且字符集/排序规则正确  → 期望 1 行：utf8mb4 / utf8mb4_0900_ai_ci
SELECT SCHEMA_NAME, DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME
FROM information_schema.SCHEMATA
WHERE SCHEMA_NAME = 'kangji_healthtrack_test';

-- V2) 测试库当前表数  → 期望 **0**（迁移尚未执行；迁移由工程侧随 B1-R-FIX 第 3b 层执行）
SELECT COUNT(*) AS test_table_count
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'kangji_healthtrack_test';

-- V3) kangji_dev 的授权  → 期望**出现新增一行**：
--       GRANT ALL PRIVILEGES ON `kangji_healthtrack_test`.* TO `kangji_dev`@`localhost`
--     且**原有两行保持不变**：
--       GRANT USAGE ON *.* TO `kangji_dev`@`localhost`
--       GRANT ALL PRIVILEGES ON `kangji_healthtrack`.* TO `kangji_dev`@`localhost`
SHOW GRANTS FOR 'kangji_dev'@'localhost';

-- V4) 开发库仍然存在  → 期望 1 行：kangji_healthtrack / utf8mb4 / utf8mb4_0900_ai_ci
SELECT SCHEMA_NAME, DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME
FROM information_schema.SCHEMATA
WHERE SCHEMA_NAME = 'kangji_healthtrack';

-- V5) 开发库**未被修改**：表数  → 期望 **11**
SELECT COUNT(*) AS dev_table_count
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'kangji_healthtrack';

-- V6) 开发库**未被修改**：逐表行数（B1-R-FIX 第 2 层 BEFORE 快照，2026-09-24 只读实测）
--     期望：4 / 3 / 100 / 2 / 12 / 67 / 3 / 1 / 0 / 0
SELECT
  (SELECT COUNT(*) FROM `kangji_healthtrack`.user_account)         AS user_account,
  (SELECT COUNT(*) FROM `kangji_healthtrack`.user_profile)         AS user_profile,
  (SELECT COUNT(*) FROM `kangji_healthtrack`.health_record)        AS health_record,
  (SELECT COUNT(*) FROM `kangji_healthtrack`.record_tag)           AS record_tag,
  (SELECT COUNT(*) FROM `kangji_healthtrack`.health_goal)          AS health_goal,
  (SELECT COUNT(*) FROM `kangji_healthtrack`.user_session)         AS user_session,
  (SELECT COUNT(*) FROM `kangji_healthtrack`.login_failure_state)  AS login_failure_state,
  (SELECT COUNT(*) FROM `kangji_healthtrack`.export_job)           AS export_job,
  (SELECT COUNT(*) FROM `kangji_healthtrack`.verification_code)    AS verification_code,
  (SELECT COUNT(*) FROM `kangji_healthtrack`.password_reset_token) AS password_reset_token;

-- V7) 开发库**未被修改**：迁移版本  → 期望 0003_password_reset_email
SELECT * FROM `kangji_healthtrack`.alembic_version;

-- V8) 开发库保护账号仍在（4 行）→ 期望 4833 top001 / 4834 top002 / 4836 toptest1 / 4838 top003
SELECT id, username FROM `kangji_healthtrack`.user_account ORDER BY id;
-- ============================================================================
-- 执行完成并核对无误后，请告知「已执行成功」；
-- 工程侧将随后（且**仅**对测试库）执行：alembic upgrade head
-- ============================================================================
