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
YANDEX_DISK_ROOT = "https://cloud-api.yandex.net/v1/disk/"

#---------- Yandex.Disk ----------

def check_yandex_token(token: str) -> bool:
    """Проверяет валидность токена Яндекс.Диска."""
    try:
        response = requests.get(
            YANDEX_DISK_ROOT,
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
            YANDEX_API_BASE,
            headers={"Authorization": f"OAuth {token}"},
            params={"path": f"/{folder_name}"},
            timeout=15
        )
        # 201 - создана, 409 - уже существует
        return response.status_code in [201, 409]
    except requests.exceptions.RequestException:
        return False

def get_upload_url(token: str, disk_path: str) -> tuple[str, str] | None:
    """
    Запрашивает у Яндекс.Диска ссылку для загрузки файла.
    Возвращает (href, method) или None при ошибке.
    """
    try:
        response = requests.get(
            f"{YANDEX_API_BASE}/upload",
            headers={"Authorization": f"OAuth {token}"},
            params={"path": disk_path, "overwrite": "true"},
            timeout=15
        )
        response.raise_for_status()
        data = response.json()

        href = data.get("href")
        if not href:
            logging.error(f"Яндекс не вернул href для {disk_path}")
            return None
        return href, data.get("method", "PUT")
    
    except requests.exceptions.RequestException as e:
        logging.error(f"Не удалось получить ссылку для загрузки {disk_path}: {e}")
        return None

def send_file_to_upload_url(upload_href: str, method: str, image_data: bytes) -> bool:
    """Отправляет байты файла по полученной ссылке загрузки."""
    try:
        if method == "POST":
            response = requests.post(upload_href, data=image_data, timeout=30)
        else:
            response = requests.put(upload_href, data=image_data, timeout=30)
        return response.status_code in [200, 201, 202]
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка отправки файла: {e}")
        return False


def get_disk_file_size(token: str, disk_path: str) -> int:
    """Возвращает размер файла на Яндекс.Диске в байтах (0, если файла нет)."""
    try:
        response = requests.get(
            YANDEX_API_BASE,
            headers={"Authorization": f"OAuth {token}"},
            params={"path": disk_path},
            timeout=15
        )
        if response.status_code == 200:
            return response.json().get("size", 0)
        return 0
    except requests.exceptions.RequestException:
        return 0


def upload_to_yandex_disk(token: str, disk_path: str, image_data: bytes) -> bool:
    """
    Загружает файл на Яндекс.Диск из памяти (без сохранения на локальный диск).
    Возвращает True, если файл успешно загружен и его размер > 0.
    """
    upload_info = get_upload_url(token, disk_path)
    if not upload_info:
        return False

    upload_href, method = upload_info
    if not send_file_to_upload_url(upload_href, method, image_data):
        return False

    time.sleep(2.0)
    return get_disk_file_size(token, disk_path) > 0


#---------- Dog API ----------


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


def download_image(image_url: str) -> bytes:
    """Скачивает картинку по URL и возвращает её содержимое в байтах."""
    response = requests.get(image_url, timeout=30)
    response.raise_for_status()
    return response.content
            

#---------- Business Logic ---------


def get_targets(breed: str) -> list[tuple[str, str]]:
    """Возвращает список пар (подпорода, префикс имени файла) для загрузки."""
    subbreeds = get_subbreeds(breed)
    if not subbreeds:
        logging.info(f"У породы {breed} нет подпород, будет загружена 1 картинка")
        return [("", breed)]

    logging.info(f"Найдено подпород: {len(subbreeds)}. Загружаем по одной картинке")
    return [(sub, f"{breed}_{sub}") for sub in subbreeds]


def save_report(results: list, filename: str = "backup_report.json") -> None:
    """Сохраняет отчёт о загрузке в JSON-файл."""
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=4)
    logging.info(f"Готово. Отчет сохранен в {filename}")


def process_target(
    token: str,
    breed: str,
    subbreed: str,
    file_prefix: str,
) -> dict:
    """Скачивает одну картинку и загружает её на Яндекс.Диск. Возвращает запись отчёта."""
    try:
        image_url = get_random_image_url(breed, subbreed)
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка получения URL картинки: {e}")
        return {
            "breed": breed,
            "subbreed": subbreed if subbreed else "none",
            "status": "failed_get_url",
        }

    try:
        image_data = download_image(image_url)
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка скачивания картинки: {e}")
        return {
            "breed": breed,
            "subbreed": subbreed if subbreed else "none",
            "status": "failed_download",
        }

    filename = image_url.split("/")[-1]
    full_filename = f"{file_prefix}_{filename}"
    disk_path = f"/{breed}/{full_filename}"

    success = upload_to_yandex_disk(token, disk_path, image_data)

    if success:
        logging.info(f"Загружено: {full_filename} ({len(image_data)} байт)")
    else:
        logging.error(f"Ошибка загрузки: {full_filename}")

    return {
        "breed": breed,
        "subbreed": subbreed if subbreed else "none",
        "source_url": image_url,
        "disk_path": disk_path,
        "filename": full_filename,
        "size_bytes": len(image_data),
        "status": "success" if success else "failed",
    }


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
    try:
        targets = get_targets(breed)
    except requests.exceptions.RequestException as e:
        logging.error(f"Не удалось получить список подпород для '{breed}': {e}")
        return

    logging.info(f"Создание папки /{breed} на Яндекс.Диске...")
    if not create_yandex_folder(token, breed):
        logging.error("Не удалось создать или проверить папку на Яндекс.Диске")
        return
    logging.info("Папка готова к работе")

    results = []
    print("\n")
    for subbreed, file_prefix in tqdm(targets, desc="Загрузка картинок"):
        record = process_target(token, breed, subbreed, file_prefix)
        results.append(record)
        time.sleep(1)

    save_report(results)


if __name__ == "__main__":
    main()