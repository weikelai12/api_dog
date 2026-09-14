import requests
import json
import logging
import time
from tqdm import tqdm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S"
)

DOG_API_BASE = "https://dog.ceo/api"
YANDEX_API_BASE = "https://cloud-api.yandex.net/v1/disk/resources"


def check_yandex_token(token: str) -> bool:
    """Проверяет валидность токена Яндекс.Диска."""
    try:
        response = requests.get(
            "https://cloud-api.yandex.net/v1/disk/",
            headers={"Authorization": f"OAuth {token}"},
            timeout=15
        )
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False


def create_yandex_folder(token: str, folder_name: str) -> bool:
    """Создает папку на Яндекс.Диске. Возвращает True при успехе."""
    try:
        response = requests.put(
            f"{YANDEX_API_BASE}",
            headers={"Authorization": f"OAuth {token}"},
            params={"path": f"/{folder_name}"},
            timeout=15
        )
        # 201 - создана, 409 - уже существует
        return response.status_code in [201, 409]
    except requests.exceptions.RequestException:
        return False


def get_subbreeds(breed: str) -> list:
    """Получает список подпород для указанной породы через dog.ceo API."""
    url = f"{DOG_API_BASE}/breed/{breed}/list"
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    return response.json()["message"]


def get_random_image_url(breed: str, subbreed: str = "") -> str:
    """Получает URL случайной картинки породы или её подпороды."""
    if subbreed:
        url = f"{DOG_API_BASE}/breed/{breed}/{subbreed}/images/random"
    else:
        url = f"{DOG_API_BASE}/breed/{breed}/images/random"
    
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    return response.json()["message"]


def upload_to_yandex_disk(token: str, disk_path: str, image_data: bytes) -> bool:
    """
    Загружает файл на Яндекс.Диск из памяти (без сохранения на локальный диск).
    Возвращает True, если файл успешно загружен и его размер > 0.
    """
    headers = {"Authorization": f"OAuth {token}"}
    params = {"path": disk_path, "overwrite": "true"}
    
    try:
        response = requests.get(
            f"{YANDEX_API_BASE}/upload", 
            headers=headers, 
            params=params, 
            timeout=15
        )
        response.raise_for_status()
        
        upload_data = response.json()
        upload_href = upload_data.get("href")
        method = upload_data.get("method", "PUT")
        
        if method == "POST":
            upload_response = requests.post(upload_href, data=image_data, timeout=30)
        else:
            upload_response = requests.put(upload_href, data=image_data, timeout=30)
        
        if upload_response.status_code in [200, 201, 202]:
            time.sleep(2.0)
            
            check_response = requests.get(
                f"{YANDEX_API_BASE}",
                headers=headers,
                params={"path": disk_path},
                timeout=15
            )
            
            if check_response.status_code == 200:
                file_info = check_response.json()
                return file_info.get("size", 0) > 0
        
        return False
            
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка при загрузке {disk_path}: {e}")
        return False


def main():
    logging.info("Запуск программы резервного копирования")
    
    breed = input("Введите название породы (например, spaniel): ").strip().lower()
    token = input("Введите токен Яндекс.Диска: ").strip()
    
    if not breed or not token:
        logging.error("Название породы и токен не могут быть пустыми")
        return

    logging.info("Проверка токена Яндекс.Диска...")
    if not check_yandex_token(token):
        logging.error("Ошибка авторизации. Токен неверный или не имеет прав на запись.")
        return
    
    logging.info("Токен действителен, начинаем работу")

    logging.info(f"Поиск подпород для: {breed}")
    subbreeds = get_subbreeds(breed)
    
    if not subbreeds:
        logging.info(f"У породы {breed} нет подпород, будет загружена 1 картинка")
        targets = [("", breed)]
    else:
        logging.info(f"Найдено подпород: {len(subbreeds)}. Загружаем по одной картинке")
        targets = [(sub, f"{breed}_{sub}") for sub in subbreeds]

    logging.info(f"Создание папки /{breed} на Яндекс.Диске...")
    if not create_yandex_folder(token, breed):
        logging.error("Не удалось создать или проверить папку на Яндекс.Диске")
        return
    logging.info("Папка готова к работе")

    results = []
    
    print("\n")
    for subbreed, file_prefix in tqdm(targets, desc="Загрузка картинок"):
        image_url = get_random_image_url(breed, subbreed)
        
        try:
            img_response = requests.get(image_url, timeout=30)
            img_response.raise_for_status()
            image_data = img_response.content
        except requests.exceptions.RequestException as e:
            logging.error(f"Ошибка скачивания картинки: {e}")
            results.append({
                "breed": breed, 
                "subbreed": subbreed if subbreed else "none", 
                "status": "failed_download"
            })
            continue
        
        filename = image_url.split("/")[-1]
        full_filename = f"{file_prefix}_{filename}"
        disk_path = f"/{breed}/{full_filename}"
        
        success = upload_to_yandex_disk(token, disk_path, image_data)
        
        results.append({
            "breed": breed,
            "subbreed": subbreed if subbreed else "none",
            "source_url": image_url,
            "disk_path": disk_path,
            "filename": full_filename,
            "size_bytes": len(image_data),
            "status": "success" if success else "failed"
        })
        
        if success:
            logging.info(f"Загружено: {full_filename} ({len(image_data)} байт)")
        else:
            logging.error(f"Ошибка загрузки: {full_filename}")
        
        time.sleep(1)

    json_filename = "backup_report.json"
    with open(json_filename, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=4)
        
    logging.info(f"Готово. Отчет сохранен в {json_filename}")


if __name__ == "__main__":
    main()