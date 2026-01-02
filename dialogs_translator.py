import argparse
import asyncio
import json
import logging
import os

import aiofiles
from googletrans import Translator  # pip install googletrans==4.0.0rc1
from tqdm import tqdm

from print_neatly import print_neatly

logging.basicConfig(
    level=logging.WARNING,
    filename="app.log",
    filemode="w",
    format="%(asctime)s %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


async def translate(
    file_path, tr, src="it", dst="en", verbose=False, max_retries=5
):

    async def translate_sentence(text):
        target = text
        translation = (await tr.translate(target, src=src, dest=dst)).text
        if (
            target[0].isalpha()
            and translation[0].isalpha
            and not target[0].isupper()
        ):
            translation = translation[0].lower() + translation[1:]
        text = translation
        if verbose:
            logger.info(f"{target} -> {translation}")
        return text

    async def try_translate_sentence(text):
        try:
            return (await translate_sentence(text), True)
        except:
            for _ in range(max_retries):
                try:
                    await asyncio.sleep(1)
                    return (await translate_sentence(text), True)
                except:
                    pass
            return (text, False)

    async def translate_list(page_list):
        nonlocal translations
        async with translate_lock:
            # Plain text (ex: ["plain text"])
            if page_list["code"] == 401:
                # null or empty string check
                if not page_list["parameters"][0]:
                    return
                # translate
                (
                    page_list["parameters"][0],
                    success,
                ) = await try_translate_sentence(page_list["parameters"][0])
                if not success:
                    logger.warning(
                        f"Anomaly plain text: {page_list['parameters'][0]}"
                    )
                else:
                    translations += 1

            # Choices (ex: [["yes", "no"], 1, 0, 2, 0])
            elif page_list["code"] == 102:
                # null or empty list check
                if not page_list["parameters"][0]:
                    return
                # translate list
                for j, choice in enumerate(page_list["parameters"][0]):
                    # null or empty string check
                    if not choice:
                        return
                    # translate
                    (
                        page_list["parameters"][0][j],
                        success,
                    ) = await try_translate_sentence(choice)
                    if not success:
                        logger.warning(f"Anomaly choices: {choice}")
                    else:
                        translations += 1

            # Choices (answer) (ex: [0, "yes"])
            elif page_list["code"] == 402:
                # invalid length null or empty string check
                if (
                    len(page_list["parameters"]) != 2
                    or not page_list["parameters"][1]
                ):
                    logger.warning(
                        f"Anomaly choices (answer) - Unexpected 402 Code: {page_list['parameters']}"
                    )
                    return
                # translate
                (
                    page_list["parameters"][1],
                    success,
                ) = await try_translate_sentence(page_list["parameters"][1])
                if not success:
                    logger.warning(
                        f"Anomaly choices (answer): {page_list['parameters'][1]}"
                    )
                else:
                    translations += 1

    translations = 0
    translate_lock = asyncio.Lock()
    async with aiofiles.open(file_path, "r", encoding="utf-8-sig") as datafile:
        data = json.loads(await datafile.read())
    num_events = len([e for e in data["events"] if e is not None])
    i = 0
    async with asyncio.TaskGroup() as tg:
        for event in data["events"]:
            if event is None:
                continue
            logger.info(f"{file_path}: {i + 1}/{num_events}")
            i += 1
            for page in event["pages"]:
                for page_list in page["list"]:
                    tg.create_task(translate_list(page_list))
    return data, translations


async def translate_neatly(
    file_path, tr, src="it", dst="en", verbose=False, max_len=40, max_retries=5
):
    async def translate_sentence(text):
        target = text
        translation = (await tr.translate(target, src=src, dest=dst)).text
        if (
            target[0].isalpha()
            and translation[0].isalpha
            and not target[0].isupper()
        ):
            translation = translation[0].lower() + translation[1:]
        text = translation
        return text

    async def try_translate_sentence(text):
        try:
            return (await translate_sentence(text), True)
        except:
            for _ in range(max_retries):
                try:
                    await asyncio.sleep(1)
                    return (await translate_sentence(text), True)
                except:
                    pass
            return (text, False)

    async def translate_list(page_list, page_list_i: int, page):
        nonlocal translations, code_401_text, was_401
        async with translate_neatly_lock:
            if was_401 and page_list["code"] != 401:
                text = " ".join(code_401_text)
                if not text:
                    return
                # translate
                text_tr, success = await try_translate_sentence(text)
                if (not success) or (text_tr is None):
                    logger.warning(f"Anomaly: {text}")
                else:
                    try:
                        text_neat = print_neatly(text_tr, max_len)
                    except:
                        text_neat = text_tr
                    for text_it, j in enumerate(
                        range(
                            page_list_i - len(code_401_text),
                            page_list_i,
                        )
                    ):
                        translations += 1
                        if text_it >= len(
                            text_neat
                        ):  # translated text is one row shorter
                            text_neat.append(
                                f"{page['list'][j]['parameters'][0]} -> {text_neat[text_it]}"
                            )
                        if verbose:
                            logging.debug(
                                f"{page['list'][j]['parameters'][0]} -> {text_neat[text_it]}"
                            )
                        page["list"][j]["parameters"][0] = text_neat[text_it]
                was_401 = False
                code_401_text = []
            # 102 Choices (dont nestly translate) (ex: [["yes", "no"], 1, 0, 2, 0])
            if page_list["code"] == 102:
                # null or empty list check
                if not page_list["parameters"][0]:
                    return
                # translate list
                for j, choice in enumerate(page_list["parameters"][0]):
                    # null or empty string check
                    if not choice:
                        logger.warning(
                            f"Anomaly choices - Unexpected 102 code: {choice}"
                        )
                        continue
                    # translate
                    (
                        page_list["parameters"][0][j],
                        success,
                    ) = await try_translate_sentence(choice)
                    if not success:
                        logger.warning(f"Anomaly choices: {choice}")
                    else:
                        translations += 1

            # 402 Choices (answer) (dont nestly translate) (ex: [0, "yes"])
            elif page_list["code"] == 402:
                # invalid length null or empty string check
                if (
                    len(page_list["parameters"]) != 2
                    or not page_list["parameters"][1]
                ):
                    logger.warning(
                        f"Anomaly choices (answer) - Unexpected 402 Code: {page_list['parameters']}"
                    )
                    return
                # translate
                page_list["parameters"][1], success = (
                    await try_translate_sentence(page_list["parameters"][1])
                )
                if not success:
                    logger.warning(
                        f"Anomaly choices (answer): {page_list['parameters'][1]}"
                    )
                else:
                    translations += 1

            # 401 Plain text (to nestly translate) (ex: ["plain text"])
            elif page_list["code"] == 401:
                was_401 = True
                code_401_text.append(page_list["parameters"][0])
                return

    translations = 0
    translate_neatly_lock = asyncio.Lock()
    async with aiofiles.open(file_path, "r", encoding="utf-8-sig") as datafile:
        data = json.loads(await datafile.read())
    num_events = len([e for e in data["events"] if e is not None])
    i = 0
    async with asyncio.TaskGroup() as tg:
        for event in data["events"]:
            if event is None:
                continue
            logger.info(f"{file_path}: {i + 1}/{num_events}")
            i += 1
            for page in event["pages"]:
                was_401 = False
                code_401_text: list[str] = []
                for page_list_i, page_list in enumerate(page["list"]):
                    tg.create_task(
                        translate_list(page_list, page_list_i, page)
                    )

    return data, translations


async def translate_neatly_common_events(
    file_path, tr, src="it", dst="en", verbose=False, max_len=55, max_retries=5
):

    async def translate_sentence(text):
        target = text
        translation = (await tr.translate(target, src=src, dest=dst)).text
        if (
            target[0].isalpha()
            and translation[0].isalpha
            and not target[0].isupper()
        ):
            translation = translation[0].lower() + translation[1:]
        text = translation
        return text

    async def translate_list(event_list, event_list_i: int, d):
        nonlocal was_401, code_401_text, translations
        async with translate_common_events:
            if "code" not in event_list.keys():
                return
            if was_401 and event_list["code"] != 401:
                text = " ".join(code_401_text)
                if not text:
                    return
                text_tr = None
                try:
                    text_tr = await translate_sentence(text)
                except:
                    for _ in range(max_retries):
                        try:
                            await asyncio.sleep(1)
                            text_tr = await translate_sentence(text)
                        except:
                            pass
                        if text_tr is not None:
                            return
                if text_tr is None:
                    logger.warning(f"Anomaly: {text}")
                else:
                    try:
                        text_neat = print_neatly(text_tr, max_len)
                    except:
                        text_neat = text_tr
                    for text_it, j in enumerate(
                        range(event_list_i - len(code_401_text), event_list_i)
                    ):
                        translations += 1
                        if text_it >= len(text_neat):
                            text_neat.append("")
                        if verbose:
                            logger.debug(
                                f"{d['list'][j]['parameters'][0]} -> {text_neat[text_it]}"
                            )
                        d["list"][j]["parameters"][0] = text_neat[text_it]
                was_401 = False
                code_401_text = []
            if event_list["code"] == 401:
                was_401 = True
                code_401_text.append(event_list["parameters"][0])

    translations = 0
    translate_common_events = asyncio.Lock()
    async with aiofiles.open(file_path, "r", encoding="utf-8-sig") as datafile:
        data = json.loads(await datafile.read())
    num_ids = len([e for e in data if e is not None])
    i = 0
    async with asyncio.TaskGroup() as tg:
        for d in data:
            if d is None:
                continue
            logger.info(f"{file_path}: {i + 1}/{num_ids}")
            i += 1
            was_401 = False
            code_401_text: list[str] = []
            for event_list_i, event_list in enumerate(d["list"]):
                tg.create_task(translate_list(event_list, event_list_i, d))
    return data, translations


async def main():
    async def translate_file(file: str, pbar: tqdm):
        nonlocal translations
        file_path = os.path.join(args.input_folder, file)
        if os.path.isfile(os.path.join(dest_folder, file)):
            logger.info(
                f"skipped file {file_path} because it has already been translated"
            )
            return
        if file.endswith(".json"):
            logger.info(f"translating file: {file_path}")
            if file.startswith("Map"):
                if args.print_neatly:
                    new_data, t = await translate_neatly(
                        file_path,
                        tr=Translator(),
                        max_len=args.max_len,
                        src=args.source_lang,
                        dst=args.dest_lang,
                        verbose=args.verbose,
                        max_retries=args.max_retries,
                    )
                else:
                    new_data, t = await translate(
                        file_path,
                        tr=Translator(),
                        src=args.source_lang,
                        dst=args.dest_lang,
                        verbose=args.verbose,
                        max_retries=args.max_retries,
                    )
            elif file.startswith("CommonEvents"):
                new_data, t = await translate_neatly_common_events(
                    file_path,
                    tr=Translator(),
                    max_len=args.max_len,
                    src=args.source_lang,
                    dst=args.dest_lang,
                    verbose=args.verbose,
                    max_retries=args.max_retries,
                )
            async with lock:
                translations += t
            new_file = os.path.join(dest_folder, file)
            async with aiofiles.open(new_file, "w", encoding="utf-8") as f:
                if not args.no_format:
                    await f.write(
                        json.dumps(new_data, indent=4, ensure_ascii=False)
                    )
                else:
                    await f.write(json.dumps(new_data, ensure_ascii=False))
        pbar.update(1)

    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input_folder", type=str, default="dialogs")
    ap.add_argument("-sl", "--source_lang", type=str, default="it")
    ap.add_argument("-dl", "--dest_lang", type=str, default="en")
    ap.add_argument("-v", "--verbose", action="store_true", default=False)
    ap.add_argument("-nf", "--no_format", action="store_true", default=False)
    ap.add_argument(
        "-pn", "--print_neatly", action="store_true", default=False
    )
    ap.add_argument("-ml", "--max_len", type=int, default=44)
    ap.add_argument("-mr", "--max_retries", type=int, default=10)
    args = ap.parse_args()
    dest_folder = args.input_folder + "_" + args.dest_lang
    translations = 0
    lock = asyncio.Lock()
    input_files = os.listdir(args.input_folder)
    if not os.path.exists(dest_folder):
        os.makedirs(dest_folder)
    with tqdm(total=len(input_files), desc="Overall") as pbar:
        async with asyncio.TaskGroup() as tg:
            for file in input_files:
                tg.create_task(translate_file(file, pbar))
    logger.info(f"\ndone! translated in total {translations} dialog windows")


# usage: python dialogs_translator.py --print_neatly --source_lang it --dest_lang en
if __name__ == "__main__":
    asyncio.run(main())
