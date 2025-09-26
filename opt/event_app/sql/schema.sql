DROP TABLE IF EXISTS event_participants CASCADE;
DROP TABLE IF EXISTS event_contractors CASCADE;
DROP TABLE IF EXISTS event_reports CASCADE;
DROP TABLE IF EXISTS resource_bookings CASCADE;
DROP TABLE IF EXISTS events CASCADE;
DROP TABLE IF EXISTS external_contractors CASCADE;
DROP TABLE IF EXISTS user_roles CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TABLE IF EXISTS roles CASCADE;
DROP TABLE IF EXISTS employees CASCADE;
DROP TABLE IF EXISTS rooms CASCADE;
DROP TABLE IF EXISTS room_types CASCADE;
DROP TABLE IF EXISTS event_types CASCADE;
DROP TABLE IF EXISTS event_statuses CASCADE;
DROP TABLE IF EXISTS age_categories CASCADE;
DROP TABLE IF EXISTS positions CASCADE;

-- Расширение для временных интервалов
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Классификаторы
CREATE TABLE age_categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(20) NOT NULL UNIQUE
);

CREATE TABLE event_statuses (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE
);

-- Типы помещений и мероприятий
CREATE TABLE room_types (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE event_types (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    category VARCHAR(50) NOT NULL
);

-- Должности сотрудников
CREATE TABLE positions (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Пользователи и роли
CREATE TABLE roles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE
);

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE user_roles (
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    role_id INT REFERENCES roles(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, role_id)
);

-- Ресурсы организации
CREATE TABLE rooms (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    address VARCHAR(255) NOT NULL,
    capacity INT NOT NULL,
    description TEXT,
    room_type_id INT REFERENCES room_types(id),
    is_external BOOLEAN DEFAULT FALSE,
    image_filename VARCHAR(255),
    external_url TEXT
);

-- Сотрудники
CREATE TABLE employees (
    id SERIAL PRIMARY KEY,
    full_name VARCHAR(200) NOT NULL,
    position VARCHAR(200), -- Оставляем для обратной совместимости
    position_id INTEGER REFERENCES positions(id), -- Ссылка на таблицу positions
    contact_info TEXT,
    is_external BOOLEAN DEFAULT FALSE,
    external_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Мероприятия
CREATE TABLE events (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    max_participants INT,
    min_age_category_id INT REFERENCES age_categories(id),
    status_id INT REFERENCES event_statuses(id),
    event_type_id INT REFERENCES event_types(id),
    organizer_id INT REFERENCES users(id)
);

-- Система бронирования ресурсов
CREATE TABLE resource_bookings (
    id SERIAL PRIMARY KEY,
    event_id INT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    resource_type VARCHAR(10) NOT NULL CHECK (resource_type IN ('room', 'employee')),
    resource_id INT NOT NULL,
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    CHECK (end_time > start_time),
    
    -- Fixed exclusion constraint
    EXCLUDE USING gist (
        resource_id WITH =,
        resource_type WITH =,
        tsrange(start_time, end_time) WITH &&
    )
);

-- Внешние подрядчики (отдельная таблица)
CREATE TABLE external_contractors (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    specialty VARCHAR(100) NOT NULL,
    contact_info TEXT NOT NULL,
    rating NUMERIC(3,2) DEFAULT 0.0,
    price_per_hour NUMERIC(10,2)
);

-- Отчеты для аналитики
CREATE TABLE event_reports (
    id SERIAL PRIMARY KEY,
    event_id INT REFERENCES events(id) ON DELETE SET NULL,
    report_type VARCHAR(50) NOT NULL,
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    data JSONB NOT NULL,
    parameters JSONB NOT NULL
);

-- Связь мероприятий с внешними подрядчиками
CREATE TABLE event_contractors (
    event_id INT REFERENCES events(id) ON DELETE CASCADE,
    contractor_id INT REFERENCES external_contractors(id) ON DELETE CASCADE,
    PRIMARY KEY (event_id, contractor_id)
);

-- Связь мероприятий с сотрудниками (через бронирование)
CREATE TABLE event_participants (
    event_id INT REFERENCES events(id) ON DELETE CASCADE,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (event_id, user_id)
);

-- Таблица сессий пользователей
CREATE TABLE IF NOT EXISTS user_sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    session_token TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL
);
