import requests
from bs4 import BeautifulSoup
import logging
from typing import Dict, Optional
import sys
import io


if sys.stdout.encoding != 'UTF-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('flamp_parser.log'), logging.StreamHandler()]
)

def parse_flamp_venue(url: str) -> Optional[Dict[str, str]]:
    """
    Парсит страницу заведения на flamp.ru и возвращает структурированные данные.
    
    Args:
        url: URL заведения на flamp.ru
        
    Returns:
        Словарь с данными о заведении или None в случае ошибки
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        logging.info(f"Начинаем парсинг заведения: {url}")
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        
        name_tag = soup.find('h1', class_='header-filial__name')
        name = name_tag.text.strip() if name_tag else "Не указано"
        
        
        venue_type_tag = soup.find('div', class_='header-filial__subtitle')
        venue_type = venue_type_tag.text.strip() if venue_type_tag else "Не указано"
        
        
        average_bill_tag = soup.find('li', class_='header-filial__tag')
        average_bill = average_bill_tag.text.strip() if average_bill_tag else "Не указано"
        
        
        geo_data = soup.find('div', class_='filial-location__map')
        lat = geo_data.get('data-lat') if geo_data else None
        lon = geo_data.get('data-lon') if geo_data else None
        
        
        address_tag = soup.find('div', class_='filial-address__label')
        address = address_tag.text.strip() if address_tag else "Не указано"
        
        
        rating_tag = soup.find('div', class_='filial-rating__value')
        rating = rating_tag.text.strip() if rating_tag else "Не указано"
        
        
        reviews_count_tag = soup.find('a', class_='filial-rating__reviews')
        reviews_count = reviews_count_tag.text.strip() if reviews_count_tag else "Не указано"
        
        
        phone_tag = soup.find('a', href=lambda x: x and x.startswith('tel:'))
        phone = phone_tag.text.strip() if phone_tag else "Не указано"
        
        
        work_hours_tag = soup.find('div', class_='filial-workhours__timetable')
        work_hours = work_hours_tag.text.strip() if work_hours_tag else "Не указано"
        
        
        categories = []
        categories_block = soup.find('div', class_='filial-info-row__content')
        if categories_block:
            for item in categories_block.find_all('li', class_='list__item'):
                categories.append(item.text.strip())
        
        
        additional_info = {}
        additional_blocks = soup.find_all('div', class_='filial-info__row')
        for block in additional_blocks:
            label_tag = block.find('div', class_='l-inner__column--side')
            if label_tag:
                label = label_tag.text.strip()
                content_tag = block.find('div', class_='filial-info-row__content')
                if content_tag:
                    items = [item.text.strip() for item in content_tag.find_all('li', class_='list__item')]
                    additional_info[label] = items
        
        
        message_link_tag = soup.find('a', class_='action button-cta button-cta--thm-white-round button-cta--icon-message js-link')
        message_link = message_link_tag['href'] if message_link_tag else None
        
        
        result = {
            'name': name,
            'type': venue_type,
            'average_bill': average_bill,
            'latitude': lat,
            'longitude': lon,
            'address': address,
            'rating': rating,
            'reviews_count': reviews_count,
            'phone': phone,
            'work_hours': work_hours,
            'categories': categories,
            'additional_info': additional_info,
            'message_link': message_link,
            'source_url': url
        }
        
        logging.info("Парсинг заведения успешно завершен")
        return result
        
    except Exception as e:
        logging.error(f"Ошибка при парсинге заведения: {e}", exc_info=True)
        return None

def format_for_db(data: Dict[str, str]) -> Dict[str, str]:
    """
    Форматирует данные из парсера для сохранения в БД.
    
    Args:
        data: Сырые данные из парсера
        
    Returns:
        Данные в формате для БД
    """
    if not data:
        return None
        
    
    capacity = 50  
    
    if 'average_bill' in data:
        if 'до 500 ₽' in data['average_bill']:
            capacity = 100
        elif '500–1000 ₽' in data['average_bill']:
            capacity = 70
        elif 'от 1000 ₽' in data['average_bill']:
            capacity = 40
    
    return {
        'name': data.get('name', 'Неизвестно'),
        'address': data.get('address', 'Не указано'),
        'capacity': capacity,
        'description': f"{data.get('type', '')}. {', '.join(data.get('categories', []))}",
        'room_type_id': 1,  
        'is_external': True,
        'image_filename': None,
        'external_data': data  
    }

if __name__ == "__main__":
    
    test_url = "https://irkutsk.flamp.ru/firm/cherdak_nochnojj_klub-1548640652947676"
    
    print("Запуск парсера flamp.ru в тестовом режиме...")
    print(f"Парсим заведение: {test_url}")
    
    result = parse_flamp_venue(test_url)
    if result:
        print("\nРезультат парсинга:")
        for key, value in result.items():
            if key not in ['additional_info', 'categories']:
                print(f"{key}: {value}")
        
        print("\nКатегории:", ", ".join(result.get('categories', [])))
        print("\nДополнительная информация:")
        for key, value in result.get('additional_info', {}).items():
            print(f"{key}: {', '.join(value)}")
        
        print("\nФорматированные данные для БД:")
        db_data = format_for_db(result)
        for key, value in db_data.items():
            if key != 'external_data':
                print(f"{key}: {value}")
    else:
        print("Не удалось распарсить заведение")