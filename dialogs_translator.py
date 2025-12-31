import argparse
import asyncio
import copy
import json
import os

import tqdm
from googletrans import Translator  # pip install googletrans==4.0.0rc1

from print_neatly import print_neatly


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
            print(target, "->", translation)
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

    translations = 0
    with open(file_path, "r", encoding="utf-8-sig") as datafile:
        data = json.load(datafile)
    num_events = len([e for e in data["events"] if e is not None])
    i = 0
    for events in data["events"]:
        if events is not None:
            print("{}: {}/{}".format(file_path, i + 1, num_events))
            i += 1
            for pages in events["pages"]:
                for list in pages["list"]:

                    # Plain text (ex: ["plain text"])
                    if list["code"] == 401:
                        # null or empty string check
                        if not list["parameters"][0]:
                            continue
                        # translate
                        (
                            list["parameters"][0],
                            success,
                        ) = await try_translate_sentence(list["parameters"][0])
                        if not success:
                            print(
                                "Anomaly plain text: {}".format(
                                    list["parameters"][0]
                                )
                            )
                        else:
                            translations += 1

                    # Choices (ex: [["yes", "no"], 1, 0, 2, 0])
                    elif list["code"] == 102:
                        # null or empty list check
                        if not list["parameters"][0]:
                            continue
                        # translate list
                        for j, choice in enumerate(list["parameters"][0]):
                            # null or empty string check
                            if not choice:
                                continue
                            # translate
                            (
                                list["parameters"][0][j],
                                success,
                            ) = await try_translate_sentence(choice)
                            if not success:
                                print("Anomaly choices: {}".format(choice))
                            else:
                                translations += 1

                    # Choices (answer) (ex: [0, "yes"])
                    elif list["code"] == 402:
                        # invalid length null or empty string check
                        if (
                            len(list["parameters"]) != 2
                            or not list["parameters"][1]
                        ):
                            print(
                                "Anomaly choices (answer) - Unexpected 402 Code: {}".format(
                                    list["parameters"]
                                )
                            )
                            continue
                        # translate
                        (
                            list["parameters"][1],
                            success,
                        ) = await try_translate_sentence(list["parameters"][1])
                        if not success:
                            print(
                                "Anomaly choices (answer): {}".format(
                                    list["parameters"][1]
                                )
                            )
                        else:
                            translations += 1
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

    async def translate_list(page_list, page_list_i: int):
        nonlocal translations, code_401_text, was_401
        async with translate_neatly_lock:
            if was_401 and page_list["code"] != 401:
                text = " ".join(code_401_text)
                if not text:
                    return
                # translate
                text_tr, success = await try_translate_sentence(text)
                if (not success) or (text_tr is None):
                    print("Anomaly: {}".format(text))
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
                            text_neat.append("")
                        if verbose:
                            print(
                                pages["list"][j]["parameters"][0],
                                "->",
                                text_neat[text_it],
                            )
                        pages["list"][j]["parameters"][0] = text_neat[text_it]
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
                        print(
                            "Anomaly choices - Unexpected 102 code: {}".format(
                                choice
                            )
                        )
                        continue
                    # translate
                    (
                        page_list["parameters"][0][j],
                        success,
                    ) = await try_translate_sentence(choice)
                    if not success:
                        print("Anomaly choices: {}".format(choice))
                    else:
                        translations += 1

            # 402 Choices (answer) (dont nestly translate) (ex: [0, "yes"])
            elif page_list["code"] == 402:
                # invalid length null or empty string check
                if (
                    len(page_list["parameters"]) != 2
                    or not page_list["parameters"][1]
                ):
                    print(
                        "Anomaly choices (answer) - Unexpected 402 Code: {}".format(
                            page_list["parameters"]
                        )
                    )
                    return
                # translate
                page_list["parameters"][1], success = (
                    await try_translate_sentence(page_list["parameters"][1])
                )
                if not success:
                    print(
                        "Anomaly choices (answer): {}".format(
                            page_list["parameters"][1]
                        )
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
    with open(file_path, "r", encoding="utf-8-sig") as datafile:
        data = json.load(datafile)
    num_events = len([e for e in data["events"] if e is not None])
    i = 0
    for events in data["events"]:
        if events is None:
            continue
        print("{}: {}/{}".format(file_path, i + 1, num_events))
        i += 1
        for pages in events["pages"]:
            was_401 = False
            code_401_text: list[str] = []

            async with asyncio.TaskGroup() as tg:
                for page_list_i, page_list in enumerate(pages["list"]):
                    tg.create_task(translate_list(page_list, page_list_i))

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

    async def translate_list(event_list, event_list_i: int):
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
                            text_tr = translate_sentence(text)
                        except:
                            pass
                        if text_tr is not None:
                            return
                if text_tr is None:
                    print("Anomaly: {}".format(text))
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
                            print(
                                d["list"][j]["parameters"][0],
                                "->",
                                text_neat[text_it],
                            )
                        d["list"][j]["parameters"][0] = text_neat[text_it]
                was_401 = False
                code_401_text = []
            if event_list["code"] == 401:
                was_401 = True
                code_401_text.append(event_list["parameters"][0])

    translations = 0
    translate_common_events = asyncio.Lock()
    with open(file_path, "r", encoding="utf-8-sig") as datafile:
        data = json.load(datafile)
    num_ids = len([e for e in data if e is not None])
    i = 0
    for d in data:
        if d is None:
            continue
        print("{}: {}/{}".format(file_path, i + 1, num_ids))
        i += 1
        was_401 = False
        code_401_text: list[str] = []
        async with asyncio.TaskGroup() as tg:
            for event_list_i, event_list in enumerate(d["list"]):
                tg.create_task(translate_list(event_list, event_list_i))
    return data, translations


async def main():
    async def translate_file(file: str):
        nonlocal translations
        file_path = os.path.join(args.input_folder, file)
        if os.path.isfile(os.path.join(dest_folder, file)):
            print(
                "skipped file {} because it has already been translated".format(
                    file_path
                )
            )
            return
        if file.endswith(".json"):
            print("translating file: {}".format(file_path))
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
            with open(new_file, "w", encoding="utf-8") as f:
                if not args.no_format:
                    json.dump(new_data, f, indent=4, ensure_ascii=False)
                else:
                    json.dump(new_data, f, ensure_ascii=False)

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
    if not os.path.exists(dest_folder):
        os.makedirs(dest_folder)
    async with asyncio.TaskGroup() as tg:
        for file in os.listdir(args.input_folder):
            tg.create_task(translate_file(file))
    print("\ndone! translated in total {} dialog windows".format(translations))


# usage: python dialogs_translator.py --print_neatly --source_lang it --dest_lang en
if __name__ == "__main__":
    asyncio.run(main())
