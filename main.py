import requests
import json
import logging
from tqdm import tqdm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S"
)

DOG_API_BASE = "https://dog.ceo/api"
YANDEX_API_BASE = "https://cloud-api.yandex.net/v1/disk/resources"


def get_subbreeds(breed: str) -> list:
    url: str = f"{DOG_API_BASE}/breed/{breed}/list"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()["message"]


def get_random_image_url(breed: str, subbreed: str = "") -> str:
    
    if subbreed:
        url = f"{DOG_API_BASE}/breed/{breed}/{subbreed}/images/random"
    else:
        url = f"{DOG_API_BASE}/breed/{breed}/images/random"
        
    response = requests.get(url)
    response.raise_for_status()
    return response.json()["message"]


def upload_to_yandex_disk(token: str, disk_path: str, source_url: str) -> bool:
    
    headers = {"Authorization": f"OAuth {token}"}
    params = {
        "path": disk_path,
        "url": source_url,
        "overwrite": "true"
    }
    
    try:
        response = requests.get(f"{YANDEX_API_BASE}/upload", headers=headers, params=params)
        response.raise_for_status()
        
        upload_data = response.json()
        upload_href = upload_data.get("href")
        method = upload_data.get("method", "POST")
        
        if method == "POST":
            upload_response = requests.post(upload_href)
        else:
            upload_response = requests.put(upload_href)
            
        return upload_response.status_code in [201, 202]
            
    except requests.exceptions.RequestException as e:
        logging.error(f"Сетевая ошибка при загрузке {disk_path}: {e}")
        return False


def main():
    logging.info("=== Запуск программы резервного копирования собак ===")
    
    breed = input("Введите название породы (например, spaniel): ").strip().lower()
    token = input("Введите токен Яндекс.Диска: ").strip()
    
    if not breed or not token:
        logging.error("Название породы и токен не могут быть пустыми!")
        return

    
    logging.info("Проверка токена Яндекс.Диска...")
    logging.info(f"Длина токена: {len(token)} символов")
    logging.info(f"Начало токена: {token[:10]}...")
    logging.info(f"Конец токена: ...{token[-10:]}")
    
    test_response = requests.get(
        "https://cloud-api.yandex.net/v1/disk/", 
        headers={"Authorization": f"OAuth {token}"}
    )
    
    if test_response.status_code != 200:
        logging.error(f"ОШИБКА АВТОРИЗАЦИИ! (Код: {test_response.status_code})")
        logging.error(f"Ответ сервера: {test_response.text}")
        logging.error("Возможные причины:")
        logging.error("1. Токен содержит лишние символы (пробелы, #token=, &)")
        logging.error("2. Токен скопирован не полностью")
        logging.error("3. Токен истек")
        return
    
    logging.info(" Токен действителен! Начинаем работу.")

   
    logging.info(f"Ищем подпороды для: {breed}")
    subbreeds = get_subbreeds(breed)
    
    if not subbreeds:
        logging.info(f" У породы '{breed}' нет подпород. Будет загружена 1 картинка.")
        targets = [("", breed)]
    else:
        logging.info(f"Найдено подпород: {len(subbreeds)}. Загружаем по одной картинке для каждой.")
        targets = [(sub, f"{breed}_{sub}") for sub in subbreeds]

    
    headers = {"Authorization": f"OAuth {token}"}
    requests.put(f"{YANDEX_API_BASE}", headers=headers, params={"path": f"/{breed}"})
    logging.info(f"Папка '/{breed}' проверена/создана на Яндекс.Диске.")

    
    results = []
    
    print("\n")
    for subbreed, file_prefix in tqdm(targets, desc="Загрузка картинок"):
        image_url = get_random_image_url(breed, subbreed)
        filename = image_url.split("/")[-1]
        full_filename = f"{file_prefix}_{filename}"
        disk_path = f"/{breed}/{full_filename}"
        
        success = upload_to_yandex_disk(token, disk_path, image_url)
        
        results.append({
            "breed": breed,
            "subbreed": subbreed if subbreed else "none",
            "source_url": image_url,
            "disk_path": disk_path,
            "filename": full_filename,
            "status": "success" if success else "failed"
        })
        
        if success:
            logging.info(f" Загружено: {full_filename}")
        else:
            logging.error(f" Ошибка: {full_filename}")

    
    json_filename = "backup_report.json"
    with open(json_filename, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=4)
        
    logging.info(f"=== Готово! Отчет сохранен в {json_filename} ===")


if __name__ == "__main__":
    main()