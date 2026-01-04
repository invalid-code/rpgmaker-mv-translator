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
    file_path, tr, src="it", dst="en", verbose=False, max_retries=5, max_len=55
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
            logger.debug(f"{target} -> {translation}")
        return text

    async def translate_and_check(
        text, remove_escape=True, neatly=False, keep_space=True
    ):
        text_tr = None
        if remove_escape:
            text = text.replace("\n", " ")
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
                    break
        if text_tr is None:
            logger.warning(f"Anomaly: {text}")
            return None, 0
        if neatly:
            try:
                text_neat = print_neatly(text_tr, max_len)
                if len(text_neat) > 1:
                    text_tr = text_neat[0] + "\n" + text_neat[1]
                else:
                    text_tr = text_neat[0]
            except:
                pass
        if keep_space:
            if text[0] == " " and text_tr[0] != " ":
                text_tr = " " + text_tr
        return text_tr, 1

    async def translate_based_on_keys(
        dict_or_list,
        keys,
        tg: asyncio.TaskGroup,
        translations=0,
        remove_escape=True,
        neatly=False,
        array_translate=False,
    ):
        async def translate_dict(d, dict_or_list):
            nonlocal translations
            tr, success = await translate_and_check(
                dict_or_list[d], remove_escape, neatly
            )
            dict_or_list[d] = tr
            async with translate_lock:
                translations += success

        async def translate_list(i: int, dict_or_list):
            nonlocal translations
            tr, success = await translate_and_check(
                dict_or_list[i], remove_escape, neatly
            )
            dict_or_list[i] = tr
            async with translate_lock:
                translations += success

        if isinstance(dict_or_list, dict):
            for d in dict_or_list:
                if isinstance(dict_or_list[d], dict) or isinstance(
                    dict_or_list[d], list
                ):
                    translations += await translate_based_on_keys(
                        dict_or_list[d],
                        keys,
                        tg,
                        translations,
                        remove_escape,
                        neatly,
                        array_translate,
                    )
                elif d in keys and len(dict_or_list[d]) > 0:
                    tg.create_task(translate_dict(d, dict_or_list))
        elif isinstance(dict_or_list, list):
            for i in range(len(dict_or_list)):
                if isinstance(dict_or_list[i], dict) or isinstance(
                    dict_or_list[i], list
                ):
                    translations += await translate_based_on_keys(
                        dict_or_list[i],
                        keys,
                        tg,
                        translations,
                        remove_escape,
                        neatly,
                        array_translate,
                    )
                elif (
                    array_translate
                    and isinstance(dict_or_list[i], str)
                    and len(dict_or_list[i]) > 0
                ):
                    tg.create_task(translate_list(i, dict_or_list))

        return translations

    async def translate_non_key_based(d):
        nonlocal translations, i
        if d is None:
            return
        async with translate_lock:
            logger.info("{file_path}: {i + 1}/{num_ids}")
            i += 1
        if "name" in d.keys():
            if d["name"] == "":
                return
            name_tr, success = await translate_and_check(
                d["name"], remove_escape=True, neatly=False
            )
            d["name"] = name_tr
            async with translate_lock:
                translations += success
        if "description" in d.keys():
            if d["description"] == "":
                return
            desc_tr, success = await translate_and_check(
                d["description"], remove_escape=True, neatly=True
            )
            d["description"] = desc_tr
            async with translate_lock:
                translations += success
        if "profile" in d.keys():
            if d["profile"] == "":
                return
            prf_tr, success = await translate_and_check(
                d["profile"], remove_escape=True, neatly=True
            )
            d["profile"] = prf_tr
            async with translate_lock:
                translations += success
        for m in range(1, 5):
            message = "message" + str(m)
            if message in d.keys() and len(d[message]) > 0:
                message_tr, success = await translate_and_check(
                    d[message], remove_escape=False, neatly=False
                )
                d[message] = message_tr
                async with translate_lock:
                    translations += success

    translations = 0
    async with aiofiles.open(file_path, "r", encoding="utf-8-sig") as datafile:
        data = json.loads(await datafile.read())
    num_ids = len([e for e in data if e is not None])
    i = 0
    translate_lock = asyncio.Lock()

    async with asyncio.TaskGroup() as tg:
        if file_path.endswith("GalleryList.json"):
            translations += await translate_based_on_keys(
                data,
                ["displayName", "hint", "stageText", "sceneText", "text"],
                tg,
                translations,
            )

        elif file_path.endswith("RubiList.json"):
            translations += await translate_based_on_keys(
                data,
                [],
                tg,
                translations,
                array_translate=True,
            )

        else:
            for d in data:
                tg.create_task(translate_non_key_based(d))

    return data, translations


async def main():
    async def translate_file(file, pbar: tqdm):
        nonlocal translations
        file_path = os.path.join(args.input_folder, file)
        if os.path.isfile(os.path.join(dest_folder, file)):
            logger.info(
                f"skipped file {file_path} because it has already been translated"
            )
            return
        if file.endswith(".json"):
            logger.info(f"translating file: {file_path}")
            new_data, t = await translate(
                file_path,
                tr=Translator(),
                max_len=args.max_len,
                src=args.source_lang,
                dst=args.dest_lang,
                verbose=args.verbose,
                max_retries=args.max_retries,
            )
            async with translate_file_lock:
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
    ap.add_argument("-i", "--input_folder", type=str, default="objects")
    ap.add_argument("-sl", "--source_lang", type=str, default="it")
    ap.add_argument("-dl", "--dest_lang", type=str, default="en")
    ap.add_argument("-v", "--verbose", action="store_true", default=False)
    ap.add_argument("-nf", "--no_format", action="store_true", default=False)
    ap.add_argument("-ml", "--max_len", type=int, default=55)
    ap.add_argument("-mr", "--max_retries", type=int, default=10)
    args = ap.parse_args()
    dest_folder = args.input_folder + "_" + args.dest_lang
    translations = 0
    translate_file_lock = asyncio.Lock()
    if not os.path.exists(dest_folder):
        os.makedirs(dest_folder)
    input_files = os.listdir(args.input_folder)
    with tqdm(total=len(input_files), desc="Overall") as pbar:
        async with asyncio.TaskGroup() as tg:
            for file in input_files:
                tg.create_task(translate_file(file, pbar))
    logger.info(f"\ndone! translated in total {translations} strings")


# usage: python objects_translator.py --source_lang it --dest_lang en
if __name__ == "__main__":
    asyncio.run(main())
