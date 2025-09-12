import asyncpg
import os
from pathlib import Path
from dotenv import load_dotenv
import asyncio
from passlib.context import CryptContext
from datetime import datetime, timedelta
import random

load_dotenv()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

async def drop_tables(conn):
    """Удаление всех таблиц в базе данных"""
    try:
        await conn.execute("""
            DROP TABLE IF EXISTS resource_bookings CASCADE;
            DROP TABLE IF EXISTS user_roles CASCADE;
            DROP TABLE IF EXISTS events CASCADE;
            DROP TABLE IF EXISTS rooms CASCADE;
            DROP TABLE IF EXISTS employees CASCADE;
            DROP TABLE IF EXISTS users CASCADE;
            DROP TABLE IF EXISTS roles CASCADE;
            DROP TABLE IF EXISTS age_categories CASCADE;
            DROP TABLE IF EXISTS event_statuses CASCADE;
            DROP TABLE IF EXISTS room_types CASCADE;
            DROP TABLE IF EXISTS event_types CASCADE;
        """)
        print("All tables dropped successfully")
    except Exception as e:
        print(f"Error dropping tables: {e}")
        raise

async def init_db(recreate=False):
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is not set")
    
    database_url = database_url.replace("postgresql+asyncpg://", "postgres://")
    
    conn = await asyncpg.connect(database_url)
    
    try:
        if recreate:
            await drop_tables(conn)
        
        sql_path = Path(__file__).parent / "sql" / "schema.sql"
        with open(sql_path, encoding='utf-8') as f:
            sql = f.read()
        
        await conn.execute(sql)
        print("Database schema initialized successfully")
        
        await add_test_data(conn)
        
    except Exception as e:
        print(f"Error initializing database: {e}")
        raise
    finally:
        await conn.close()

async def add_test_data(conn):
    """Добавление тестовых данных в БД"""
    print("Adding test data...")
    
    try:
        await conn.execute("""
            INSERT INTO roles (name) VALUES 
            ('Администратор'), ('Организатор'), ('Сотрудник'), ('Пользователь')
            ON CONFLICT DO NOTHING;
        """)
        
        users_data = [
            ('admin@example.com', 'admin123', 'Администратор Системы', 'admin@example.com'),
            ('org1@example.com', 'org123', 'Иванова Мария Петровна', 'org1@example.com'),
            ('org2@example.com', 'org123', 'Смирнов Алексей Владимирович', 'org2@example.com'),
            ('coord1@example.com', 'coord123', 'Петров Дмитрий Иванович', 'coord1@example.com')
        ]

        for username, password, full_name, email in users_data:
            await conn.execute("""
                INSERT INTO users (username, password_hash, full_name, email) VALUES
                ($1, $2, $3, $4)
                ON CONFLICT DO NOTHING;
            """, username, pwd_context.hash(password), full_name, email)
        
        await conn.execute("""
            INSERT INTO user_roles (user_id, role_id) VALUES
            ((SELECT id FROM users WHERE username = 'admin@example.com'), 
             (SELECT id FROM roles WHERE name = 'Администратор')),
            ((SELECT id FROM users WHERE username = 'org1@example.com'), 
             (SELECT id FROM roles WHERE name = 'Организатор')),
            ((SELECT id FROM users WHERE username = 'org2@example.com'), 
             (SELECT id FROM roles WHERE name = 'Организатор')),
            ((SELECT id FROM users WHERE username = 'coord1@example.com'), 
             (SELECT id FROM roles WHERE name = 'Сотрудник'))
            ON CONFLICT DO NOTHING;
        """)
        
        await conn.execute("""
            INSERT INTO age_categories (name) VALUES 
            ('0+'), ('6+'), ('12+'), ('16+'), ('18+'), ('21+')
            ON CONFLICT DO NOTHING;
        """)
        
        await conn.execute("""
            INSERT INTO event_statuses (name) VALUES 
            ('Запланировано'), ('Активно'), ('Завершено'), ('Отменено')
            ON CONFLICT DO NOTHING;
        """)
        
        await conn.execute("""
            INSERT INTO room_types (name) VALUES 
            ('Конференц-зал'), ('Тренинг-зал'), ('Коворкинг'), 
            ('Мультифункциональный зал'), ('Спортивный зал'), ('Кинозал'),
            ('Лекторий'), ('Выставочный зал'), ('Танцевальный зал'),
            ('Библиотека'), ('Кафе'), ('Актовый зал')
            ON CONFLICT DO NOTHING;
        """)
        
        await conn.execute("""
            INSERT INTO event_types (name, category) VALUES 
            ('Научное', 'Научное'),
            ('Деловое', 'Деловое'), 
            ('Образовательное', 'Образовательное'), 
            ('Культурно-развлекательное', 'Культурно-развлекательное'), 
            ('Культурное', 'Культурное'), 
            ('Спортивное', 'Спортивное'),
            ('Праздник', 'Праздник')
            ON CONFLICT DO NOTHING;
        """)
        
        rooms_data = [
            ('Синий зал Дом молодежи', 'Конференц-зал', 500, 'ул. Ленина, 1', 'Большой конференц-зал с проектором и звуковым оборудованием', 'blue_hall.jpg'),
            ('Красный зал Дом молодежи', 'Конференц-зал', 150, 'ул. Ленина, 1', 'Малый конференц-зал для переговоров', 'red_hall.jpg'),
            ('Коворкинг "Точка Кипения"', 'Коворкинг', 30, 'ул. Лермонтова, 83', 'Коворкинг для работы и мероприятий с зонами отдыха', 'coworking_space.jpg'),
            ('Кинозал Баргузин', 'Кинозал', 50, 'ул. Советская, 175', 'Кинозал с панорамным экраном и Dolby Surround', 'cinema_hall.jpg'),
            ('Спортивный зал Школа №21', 'Спортивный зал', 50, 'ул. Байкальская, 215', 'Спортивный зал с раздевалками и душевыми', 'sports_hall.jpg'),
            ('Актовый зал Университета', 'Актовый зал', 300, 'пр. Карла Маркса, 1', 'Большой зал для мероприятий с театральной сценой', 'assembly_hall.jpg'),
            ('Лекторий Научной библиотеки', 'Лекторий', 80, 'ул. Гагарина, 24', 'Лекционный зал с интерактивной доской', 'lecture_hall.jpg'),
            ('Выставочный зал ИркутскАрт', 'Выставочный зал', 200, 'ул. Декабрьских Событий, 102', 'Просторный зал для выставок с естественным освещением', 'exhibition_hall.jpg'),
            ('Танцевальный зал ДК Юность', 'Танцевальный зал', 40, 'ул. Байкальская, 147', 'Зал с зеркалами и станками для танцев', 'dance_studio.jpg'),
            ('Кафе "Книжный червь"', 'Кафе', 25, 'ул. Урицкого, 8', 'Уютное кафе с возможностью проведения небольших встреч', 'book_cafe.jpg')
        ]
                
        for name, room_type, capacity, address, description, image_filename in rooms_data:
            await conn.execute("""
            INSERT INTO rooms (name, room_type_id, capacity, address, description, image_filename)
            VALUES ($1, (SELECT id FROM room_types WHERE name = $2), $3, $4, $5, $6)
            ON CONFLICT DO NOTHING;
        """, name, room_type, capacity, address, description, image_filename)
        
        employees_data = [
            ('Иванов Алексей Петрович', 'Менеджер проектов', 'ivanov@example.com', False),
            ('Петрова Светлана Михайловна', 'Дизайнер мероприятий', 'petrova@example.com', False),
            ('Сидоров Дмитрий Владимирович', 'IT-специалист', 'sidorov@example.com', False),
            ('Кузнецова Елена Леонидовна', 'Координатор мероприятий', 'kuznetsova@example.com', False),
            ('Смирнов Виктор Константинович', 'Консультант по UX', 'smirnov@example.com', True),
            ('Орлова Мария Сергеевна', 'Тренер по agile', 'orlova@example.com', True),
            ('Жуков Павел Александрович', 'Архитектор решений', 'zhukov@example.com', True),
            ('Волкова Анна Дмитриевна', 'Фотограф', 'volkova@example.com', True),
            ('Лебедев Игорь Олегович', 'Видеооператор', 'lebedev@example.com', True),
            ('Соколова Ольга Игоревна', 'Ведущий мероприятий', 'sokolova@example.com', True),
            ('Козлов Михаил Андреевич', 'Звукорежиссер', 'kozlov@example.com', True),
            ('Новикова Татьяна Викторовна', 'Декоратор', 'novikova@example.com', True),
            ('Петров Дмитрий Иванович', 'Координатор мероприятий', 'coord1@example.com', False)  # Добавлен как сотрудник
        ]
        
        for full_name, position, contact_info, is_external in employees_data:
            await conn.execute("""
                INSERT INTO employees (full_name, position, contact_info, is_external)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT DO NOTHING;
            """, full_name, position, contact_info, is_external)
        
    
        events_data = [
            # Существующие мероприятия
            ('Технологическая конференция "Цифровой Байкал"', 
             'Ежегодная конференция, посвященная новейшим технологическим тенденциям и инновациям в IT-сфере. В программе: выступления ведущих экспертов, мастер-классы, нетворкинг.',
             datetime(2025, 4, 15, 9, 0), datetime(2025, 4, 17, 18, 0), 500, '16+', 'Активно', 'Научное', 'org1@example.com'),
            
            ('Корпоративный новогодний праздник', 
             'Традиционное празднование Нового года для сотрудников и партнеров компании с конкурсами, подарками и живой музыкой.',
             datetime(2025, 12, 23, 19, 0), datetime(2025, 12, 23, 23, 0), 150, '18+', 'Запланировано', 'Праздник', 'org2@example.com'),
            
            ('Мастер-класс по проектному управлению', 
             'Практический семинар для менеджеров проектов с разбором реальных кейсов и современных методик управления проектами.',
             datetime(2025, 2, 5, 10, 0), datetime(2025, 2, 6, 17, 0), 30, '18+', 'Завершено', 'Образовательное', 'org1@example.com'),
            
            ('Фестиваль молодежных инициатив', 
             'Масштабное мероприятие для активной молодежи с презентацией проектов, конкурсами и возможностью получить грантовую поддержку.',
             datetime(2025, 5, 20, 10, 0), datetime(2025, 5, 22, 20, 0), 300, '16+', 'Запланировано', 'Культурно-развлекательное', 'org2@example.com'),
            
            ('Выставка современного искусства "Арт-Волна"', 
             'Выставка работ молодых художников и скульпторов с интерактивными инсталляциями и мастер-классами.',
             datetime(2025, 3, 10, 11, 0), datetime(2025, 3, 20, 19, 0), 100, '12+', 'Активно', 'Культурное', 'org1@example.com'),
            
            ('Турнир по настольному теннису', 
             'Ежегодный турнир среди сотрудников компаний-партнеров с призовым фондом и развлекательной программой.',
             datetime(2025, 6, 12, 9, 0), datetime(2025, 6, 12, 18, 0), 50, '16+', 'Запланировано', 'Спортивное', 'org2@example.com'),
            
            ('Лекция "Будущее искусственного интеллекта"', 
             'Популярная лекция от ведущего эксперта в области ИИ о перспективах развития технологии и ее влиянии на общество.',
             datetime(2025, 7, 8, 18, 30), datetime(2025, 7, 8, 20, 30), 80, '16+', 'Запланировано', 'Образовательное', 'org1@example.com'),
            
            ('Тренинг "Эффективные коммуникации"', 
             'Двухдневный тренинг по развитию навыков делового общения и публичных выступлений.',
             datetime(2025, 8, 14, 10, 0), datetime(2025, 8, 15, 17, 0), 25, '18+', 'Запланировано', 'Образовательное', 'org2@example.com'),
            
            # Новые мероприятия на 20 апреля 2025
            ('Воркшоп по веб-разработке', 
             'Практический воркшоп для начинающих веб-разработчиков с созданием реального проекта.',
             datetime(2025, 4, 20, 10, 0), datetime(2025, 4, 20, 16, 0), 25, '16+', 'Запланировано', 'Образовательное', 'org1@example.com'),
            
            ('Концерт молодых исполнителей', 
             'Музыкальный вечер с выступлениями талантливых молодых музыкантов и певцов.',
             datetime(2025, 4, 20, 18, 0), datetime(2025, 4, 20, 22, 0), 100, '12+', 'Запланировано', 'Культурно-развлекательное', 'org2@example.com'),
            
            # Новые мероприятия на 18 февраля 2025
            ('Семинар по цифровому маркетингу', 
             'Современные тренды и инструменты цифрового маркетинга для бизнеса.',
             datetime(2025, 2, 18, 9, 0), datetime(2025, 2, 18, 13, 0), 40, '18+', 'Запланировано', 'Деловое', 'org1@example.com'),
            
            ('Тренинг по тайм-менеджменту', 
             'Эффективные методы управления временем и повышения продуктивности.',
             datetime(2025, 2, 18, 14, 0), datetime(2025, 2, 18, 18, 0), 30, '16+', 'Запланировано', 'Образовательное', 'org2@example.com'),
            
            ('Вечер настольных игр', 
             'Расслабляющий вечер с разнообразными настольными играми для всех желающих.',
             datetime(2025, 2, 18, 19, 0), datetime(2025, 2, 18, 23, 0), 50, '12+', 'Запланировано', 'Культурно-развлекательное', 'org1@example.com'),
            
            # Новые мероприятия на 9 декабря 2024
            ('Подготовка к Новому году: мастер-класс', 
             'Создание новогодних украшений и подарков своими руками.',
             datetime(2024, 12, 9, 11, 0), datetime(2024, 12, 9, 14, 0), 20, '6+', 'Запланировано', 'Праздник', 'org2@example.com'),
            
            ('Бизнес-завтрак с инвесторами', 
             'Неформальная встреча предпринимателей с потенциальными инвесторами.',
             datetime(2024, 12, 9, 9, 0), datetime(2024, 12, 9, 12, 0), 25, '18+', 'Запланировано', 'Деловое', 'org1@example.com'),
            
            ('Рождественский хоровой концерт', 
             'Традиционные рождественские песни в исполнении местного хора.',
             datetime(2024, 12, 9, 18, 0), datetime(2024, 12, 9, 20, 0), 80, '0+', 'Запланировано', 'Культурное', 'org2@example.com')
        ]
        
        for name, description, start_time, end_time, max_participants, age_category, status, event_type, organizer in events_data:
            await conn.execute("""
                INSERT INTO events (name, description, start_time, end_time, max_participants, 
                                  min_age_category_id, status_id, event_type_id, organizer_id)
                VALUES ($1, $2, $3, $4, $5, 
                       (SELECT id FROM age_categories WHERE name = $6),
                       (SELECT id FROM event_statuses WHERE name = $7),
                       (SELECT id FROM event_types WHERE name = $8),
                       (SELECT id FROM users WHERE username = $9))
                ON CONFLICT DO NOTHING;
            """, name, description, start_time, end_time, max_participants, 
               age_category, status, event_type, organizer)
        
        event_rooms = [
            # Существующие привязки
            ('Технологическая конференция "Цифровой Байкал"', 'Синий зал Дом молодежи'),
            ('Корпоративный новогодний праздник', 'Красный зал Дом молодежи'),
            ('Мастер-класс по проектному управлению', 'Коворкинг "Точка Кипения"'),
            ('Фестиваль молодежных инициатив', 'Актовый зал Университета'),
            ('Выставка современного искусства "Арт-Волна"', 'Выставочный зал ИркутскАрт'),
            ('Турнир по настольному теннису', 'Спортивный зал Школа №21'),
            ('Лекция "Будущее искусственного интеллекта"', 'Лекторий Научной библиотеки'),
            ('Тренинг "Эффективные коммуникации"', 'Коворкинг "Точка Кипения"'),
            
            # Новые привязки для мероприятий 20 апреля
            ('Воркшоп по веб-разработке', 'Коворкинг "Точка Кипения"'),
            ('Концерт молодых исполнителей', 'Актовый зал Университета'),
            
            # Новые привязки для мероприятий 18 февраля
            ('Семинар по цифровому маркетингу', 'Лекторий Научной библиотеки'),
            ('Тренинг по тайм-менеджменту', 'Коворкинг "Точка Кипения"'),
            ('Вечер настольных игр', 'Кафе "Книжный червь"'),
            
            # Новые привязки для мероприятий 9 декабря
            ('Подготовка к Новому году: мастер-класс', 'Коворкинг "Точка Кипения"'),
            ('Бизнес-завтрак с инвесторами', 'Кафе "Книжный червь"'),
            ('Рождественский хоровой концерт', 'Лекторий Научной библиотеки')
        ]
        
        for event_name, room_name in event_rooms:
            await conn.execute("""
                INSERT INTO resource_bookings (event_id, resource_type, resource_id, start_time, end_time)
                SELECT 
                    (SELECT id FROM events WHERE name = $1),
                    'room',
                    (SELECT id FROM rooms WHERE name = $2),
                    (SELECT start_time FROM events WHERE name = $1),
                    (SELECT end_time FROM events WHERE name = $1)
                WHERE NOT EXISTS (
                    SELECT 1 FROM resource_bookings 
                    WHERE event_id = (SELECT id FROM events WHERE name = $1)
                    AND resource_type = 'room'
                    AND resource_id = (SELECT id FROM rooms WHERE name = $2)
                )
            """, event_name, room_name)
        
        event_employees = [
            # Существующие привязки
            ('Технологическая конференция "Цифровой Байкал"', ['Иванов Алексей Петрович', 'Петрова Светлана Михайловна', 'Смирнов Виктор Константинович', 'Волкова Анна Дмитриевна', 'Петров Дмитрий Иванович']),
            ('Корпоративный новогодний праздник', ['Иванов Алексей Петрович', 'Сидоров Дмитрий Владимирович', 'Соколова Ольга Игоревна', 'Козлов Михаил Андреевич']),
            ('Мастер-класс по проектному управлению', ['Иванов Алексей Петрович', 'Кузнецова Елена Леонидовна', 'Орлова Мария Сергеевна', 'Петров Дмитрий Иванович']),
            ('Фестиваль молодежных инициатив', ['Петрова Светлана Михайловна', 'Кузнецова Елена Леонидовна', 'Волкова Анна Дмитриевна', 'Лебедев Игорь Олегович']),
            ('Выставка современного искусства "Арт-Волна"', ['Новикова Татьяна Викторовна', 'Волкова Анна Дмитриевна', 'Петров Дмитрий Иванович']),
            ('Турнир по настольному теннису', ['Сидоров Дмитрий Владимирович', 'Петров Дмитрий Иванович']),
            ('Лекция "Будущее искусственного интеллекта"', ['Жуков Павел Александрович', 'Соколова Ольга Игоревна']),
            ('Тренинг "Эффективные коммуникации"', ['Орлова Мария Сергеевна', 'Кузнецова Елена Леонидовна', 'Петров Дмитрий Иванович']),
            
            # Новые привязки для мероприятий
            ('Воркшоп по веб-разработке', ['Сидоров Дмитрий Владимирович', 'Жуков Павел Александрович']),
            ('Концерт молодых исполнителей', ['Козлов Михаил Андреевич', 'Волкова Анна Дмитриевна']),
            ('Семинар по цифровому маркетингу', ['Петрова Светлана Михайловна', 'Петров Дмитрий Иванович']),
            ('Тренинг по тайм-менеджменту', ['Орлова Мария Сергеевна']),
            ('Вечер настольных игр', ['Соколова Ольга Игоревна']),
            ('Подготовка к Новому году: мастер-класс', ['Новикова Татьяна Викторовна']),
            ('Бизнес-завтрак с инвесторами', ['Иванов Алексей Петрович', 'Петров Дмитрий Иванович']),
            ('Рождественский хоровой концерт', ['Козлов Михаил Андреевич'])
        ]
        
        for event_name, employees in event_employees:
            for employee_name in employees:
                await conn.execute("""
                    INSERT INTO resource_bookings (event_id, resource_type, resource_id, start_time, end_time)
                    SELECT 
                        (SELECT id FROM events WHERE name = $1),
                        'employee',
                        (SELECT id FROM employees WHERE full_name = $2),
                        (SELECT start_time FROM events WHERE name = $1),
                        (SELECT end_time FROM events WHERE name = $1)
                    WHERE NOT EXISTS (
                        SELECT 1 FROM resource_bookings 
                        WHERE event_id = (SELECT id FROM events WHERE name = $1)
                        AND resource_type = 'employee'
                        AND resource_id = (SELECT id FROM employees WHERE full_name = $2)
                    )
                """, event_name, employee_name)
        
        print("Test data added successfully")
        
    except Exception as e:
        print(f"Error adding test data: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(init_db(recreate=True))