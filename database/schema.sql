CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 0001_initial_schema

CREATE TABLE user_account (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
    username VARCHAR(20) NOT NULL, 
    password_hash VARCHAR(100) NOT NULL, 
    password_algo VARCHAR(16) NOT NULL DEFAULT 'bcrypt', 
    `role` VARCHAR(16) NOT NULL DEFAULT 'user', 
    terms_agreed_at DATETIME, 
    agreement_version VARCHAR(16), 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    PRIMARY KEY (id)
)CHARSET=utf8mb4 COMMENT='用户账号' ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE UNIQUE INDEX uk_user_account_username ON user_account (username);

CREATE TABLE user_profile (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
    user_id BIGINT UNSIGNED NOT NULL, 
    nickname VARCHAR(20), 
    gender TINYINT UNSIGNED, 
    birth_date DATE, 
    height_cm NUMERIC(5, 1), 
    initial_weight_kg NUMERIC(5, 1), 
    blood_type VARCHAR(4), 
    medical_history TEXT, 
    allergy_history TEXT, 
    medication_notes TEXT, 
    avatar_key VARCHAR(64), 
    avatar_updated_at DATETIME, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    PRIMARY KEY (id)
)CHARSET=utf8mb4 COMMENT='健康档案' ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE UNIQUE INDEX uk_user_profile_user ON user_profile (user_id);

CREATE TABLE health_record (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
    user_id BIGINT UNSIGNED NOT NULL, 
    metric_type VARCHAR(16) NOT NULL, 
    value_1 NUMERIC(10, 2), 
    value_2 NUMERIC(10, 2), 
    value_3 NUMERIC(10, 2), 
    unit VARCHAR(12) NOT NULL, 
    attr_1 VARCHAR(24), 
    attr_2 VARCHAR(24), 
    recorded_at DATETIME NOT NULL, 
    time_start DATETIME, 
    note VARCHAR(200), 
    is_deleted TINYINT UNSIGNED NOT NULL DEFAULT 0, 
    deleted_at DATETIME, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_health_record_soft_delete CHECK (is_deleted = 0 OR deleted_at IS NOT NULL)
)CHARSET=utf8mb4 COMMENT='健康记录（8 类指标单表）' ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE INDEX idx_hr_user_metric_time ON health_record (user_id, metric_type, recorded_at DESC);

CREATE INDEX idx_hr_user_time ON health_record (user_id, recorded_at DESC);

CREATE INDEX idx_hr_cleanup ON health_record (is_deleted, deleted_at);

CREATE TABLE record_tag (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
    user_id BIGINT UNSIGNED NOT NULL, 
    record_id BIGINT UNSIGNED NOT NULL, 
    tag_value VARCHAR(16) NOT NULL, 
    is_deleted TINYINT UNSIGNED NOT NULL DEFAULT 0, 
    deleted_at DATETIME, 
    created_at DATETIME NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_record_tag_soft_delete CHECK (is_deleted = 0 OR deleted_at IS NOT NULL)
)CHARSET=utf8mb4 COMMENT='记录标签（多值属性）' ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE UNIQUE INDEX uk_record_tag ON record_tag (record_id, tag_value);

CREATE INDEX idx_tag_user ON record_tag (user_id, record_id);

CREATE TABLE health_goal (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
    user_id BIGINT UNSIGNED NOT NULL, 
    goal_type VARCHAR(16) NOT NULL, 
    period_type VARCHAR(8) NOT NULL, 
    target_value NUMERIC(10, 2) NOT NULL, 
    unit VARCHAR(12) NOT NULL, 
    attr_1 VARCHAR(16), 
    start_weight_kg NUMERIC(5, 1), 
    start_date DATE NOT NULL, 
    target_date DATE, 
    status TINYINT UNSIGNED NOT NULL DEFAULT 1, 
    is_deleted TINYINT UNSIGNED NOT NULL DEFAULT 0, 
    deleted_at DATETIME, 
    deleted_marker BIGINT UNSIGNED NOT NULL DEFAULT 0, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_health_goal_soft_delete CHECK (is_deleted = 0 OR deleted_at IS NOT NULL)
)CHARSET=utf8mb4 COMMENT='健康目标' ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE UNIQUE INDEX uk_goal_user_type_active ON health_goal (user_id, goal_type, deleted_marker);

CREATE TABLE user_session (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
    user_id BIGINT UNSIGNED NOT NULL, 
    refresh_token_hash CHAR(64) NOT NULL, 
    access_token_id CHAR(64), 
    access_expires_at DATETIME NOT NULL, 
    refresh_expires_at DATETIME NOT NULL, 
    revoked_at DATETIME, 
    revoked_reason VARCHAR(24), 
    export_pwd_fail_count TINYINT UNSIGNED NOT NULL DEFAULT 0, 
    change_pwd_fail_count TINYINT UNSIGNED NOT NULL DEFAULT 0, 
    created_at DATETIME NOT NULL, 
    last_used_at DATETIME NOT NULL, 
    PRIMARY KEY (id)
)CHARSET=utf8mb4 COMMENT='用户会话 / Token 状态' ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE UNIQUE INDEX uk_session_refresh ON user_session (refresh_token_hash);

CREATE INDEX idx_session_user ON user_session (user_id, revoked_at);

CREATE INDEX idx_session_access ON user_session (access_token_id);

CREATE INDEX idx_session_refresh_exp ON user_session (refresh_expires_at);

CREATE TABLE login_failure_state (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
    username VARCHAR(20) NOT NULL, 
    fail_count TINYINT UNSIGNED NOT NULL DEFAULT 0, 
    first_fail_at DATETIME, 
    locked_until DATETIME, 
    lock_level TINYINT UNSIGNED NOT NULL DEFAULT 0, 
    updated_at DATETIME NOT NULL, 
    PRIMARY KEY (id)
)CHARSET=utf8mb4 COMMENT='登录失败与锁定状态' ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE UNIQUE INDEX uk_login_fail_username ON login_failure_state (username);

CREATE INDEX idx_login_fail_locked ON login_failure_state (locked_until);

CREATE TABLE export_job (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
    user_id BIGINT UNSIGNED NOT NULL, 
    format VARCHAR(8) NOT NULL, 
    metric_types VARCHAR(128), 
    range_start DATETIME, 
    range_end DATETIME, 
    status VARCHAR(12) NOT NULL, 
    file_token CHAR(32) NOT NULL, 
    file_path VARCHAR(255), 
    file_size_bytes INTEGER UNSIGNED, 
    record_count INTEGER UNSIGNED, 
    download_expires_at DATETIME NOT NULL, 
    purge_at DATETIME NOT NULL, 
    downloaded_at DATETIME, 
    created_at DATETIME NOT NULL, 
    PRIMARY KEY (id)
)CHARSET=utf8mb4 COMMENT='数据导出任务与临时文件' ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE UNIQUE INDEX uk_export_token ON export_job (file_token);

CREATE INDEX idx_export_user ON export_job (user_id, created_at DESC);

CREATE INDEX idx_export_purge ON export_job (purge_at, status);

INSERT INTO alembic_version (version_num) VALUES ('0001_initial_schema');

