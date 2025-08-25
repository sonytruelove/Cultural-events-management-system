import requests
from bs4 import BeautifulSoup
import logging
from typing import Dict, Optional
import sys


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('hh_parser.log'), logging.StreamHandler()]
)

def parse_hh_resume(url: str) -> Optional[Dict[str, str]]:
    """
    Парсит резюме с hh.ru и возвращает структурированные данные.
    
    Args:
        url: URL резюме на hh.ru
        
    Returns:
        Словарь с данными о кандидате или None в случае ошибки
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        logging.info(f"Начинаем парсинг резюме: {url}")
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        
        personal_info = soup.find('div', class_='resume-wrapper')
        if not personal_info:
            logging.error("Не удалось найти блок с основной информацией")
            return None
            
        
        gender_tag = personal_info.find('span', {'data-qa': 'resume-personal-gender'})
        gender = gender_tag.text.strip() if gender_tag else "Не указано"
        
        
        age_tag = personal_info.find('span', {'data-qa': 'resume-personal-age'})
        age = age_tag.text.strip() if age_tag else "Не указано"
        
        
        birthday_tag = personal_info.find('span', {'data-qa': 'resume-personal-birthday'})
        birthday = birthday_tag.text.strip() if birthday_tag else "Не указано"
        
        
        address_tag = personal_info.find('span', {'data-qa': 'resume-personal-address'})
        address = address_tag.text.strip() if address_tag else "Не указано"
        
        
        position_tag = personal_info.find('span', {'data-qa': 'resume-block-title-position'})
        position = position_tag.text.strip() if position_tag else "Не указано"
        
        
        specialization_tag = personal_info.find('li', {'data-qa': 'resume-block-position-specialization'})
        specialization = specialization_tag.text.strip() if specialization_tag else "Не указано"
        
        
        employment_info = soup.find('div', class_='resume-block-container')
        employment_type = "Не указано"
        work_schedule = "Не указано"
        
        if employment_info:
            paragraphs = employment_info.find_all('p')
            for p in paragraphs:
                text = p.text.strip()
                if "Занятость:" in text:
                    employment_type = text.replace("Занятость:", "").strip()
                elif "График работы:" in text:
                    work_schedule = text.replace("График работы:", "").strip()
        
        
        experience_section = soup.find('span', class_='resume-block__title-text_sub', string=lambda text: text and "Опыт работы" in text)
        total_experience = "Не указано"
        
        if experience_section:
            spans = experience_section.find_all('span')
            if len(spans) >= 2:
                total_experience = f"{spans[0].text.strip()} {spans[1].text.strip()}"
        
        
        last_job = {
            'period': "Не указано",
            'company': "Не указано",
            'position': "Не указаno",
            'description': "Не указано"
        }
        
        last_experience = soup.find_all('div', class_='resume-block-item-gap')
        if last_experience:
            last_job_block = last_experience[0]
            
            
            period_tag = last_job_block.find('div', class_='bloko-column_xs-4')
            if period_tag:
                last_job['period'] = period_tag.text.strip()
            
            
            company_tag = last_job_block.find('div', class_='bloko-text_strong')
            if company_tag:
                last_job['company'] = company_tag.text.strip()
            
            
            position_tag = last_job_block.find('div', {'data-qa': 'resume-block-experience-position'})
            if position_tag:
                last_job['position'] = position_tag.text.strip()
            
            
            description_tag = last_job_block.find('div', {'data-qa': 'resume-block-experience-description'})
            if description_tag:
                last_job['description'] = description_tag.text.strip().replace('<br>', '\n')
        
        
        result = {
            'gender': gender,
            'age': age,
            'birthday': birthday,
            'address': address,
            'position': position,
            'specialization': specialization,
            'employment_type': employment_type,
            'work_schedule': work_schedule,
            'total_experience': total_experience,
            'last_job': last_job,
            'source_url': url
        }
        
        logging.info("Парсинг резюме успешно завершен")
        return result
        
    except Exception as e:
        logging.error(f"Ошибка при парсинге резюме: {e}", exc_info=True)
        return None

def format_for_db(data: Dict[str, str]) -> Dict[str, str]:
    """Форматирует данные из парсера для сохранения в БД."""
    if not data:
        return None
        
    
    description = []
    if data.get('skills'):
        description.append(f"Навыки: {', '.join(data['skills'])}")
    if data.get('last_job', {}).get('position'):
        description.append(f"Последняя должность: {data['last_job']['position']}")
    if data.get('last_job', {}).get('company'):
        description.append(f"Компания: {data['last_job']['company']}")
    if data.get('last_job', {}).get('period'):
        description.append(f"Период работы: {data['last_job']['period']}")
    
    return {
        'full_name': data.get('full_name', 'Не указано'),
        'position': data.get('position', 'Не указано'),
        'contact_info': '\n'.join(data.get('contact_info', [])) if data.get('contact_info') else 'Не указано',
        'description': '\n'.join(description) if description else 'Не указано',
        'is_external': True,
        'external_url': data.get('source_url')
    }

if __name__ == "__main__":
    
    test_url = "https://hh.ru/resume/a01ed8be0003d5eb080039ed1f37704d734d4b?query=%D0%BE%D1%85%D1%80%D0%B0%D0%BD%D0%BD%D0%B8%D0%BA&searchRid=174195924470992ce3d1ca9808ead37f&hhtmFrom=resume_search_result"
    
    print("Запуск парсера hh.ru в тестовом режиме...")
    print(f"Парсим резюме: {test_url}")
    
    result = parse_hh_resume(test_url)
    if result:
        print("\nРезультат парсинга:")
        for key, value in result.items():
            print(f"{key}: {value}")
        
        print("\nФорматированные данные для БД:")
        db_data = format_for_db(result)
        for key, value in db_data.items():
            print(f"{key}: {value}")
    else:
        print("Не удалось распарсить резюме")