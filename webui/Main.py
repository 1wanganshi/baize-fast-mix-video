import os
import sys
import webbrowser
from uuid import UUID, uuid4

import requests
import streamlit as st
from loguru import logger

# Add the root directory of the project to the system path to allow importing modules from the project
root_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if root_dir not in sys.path:
    sys.path.append(root_dir)
    print("******** sys.path ********")
    print(sys.path)
    print("")

from app.config import config
from app.models.schema import (
    MaterialInfo,
    VideoAspect,
    VideoConcatMode,
    VideoParams,
    VideoTransitionMode,
)
from app.services import llm, voice
from app.utils import utils


def get_config_snapshot():
    return utils.to_json(
        {
            "app": config.app,
            "ui": config.ui,
        }
    )


def save_config_if_changed(force: bool = False):
    snapshot = get_config_snapshot()
    if force or st.session_state.get("_config_snapshot") != snapshot:
        config.save_config()
        st.session_state["_config_snapshot"] = get_config_snapshot()


st.set_page_config(
    page_title="白泽快速混剪视频",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="auto",
    menu_items=None,
)


streamlit_style = """
<style>
h1 {
    padding-top: 0 !important;
}
</style>
"""
st.markdown(streamlit_style, unsafe_allow_html=True)

# 瀹氫箟璧勬簮鐩綍
font_dir = os.path.join(root_dir, "resource", "fonts")
song_dir = os.path.join(root_dir, "resource", "songs")
i18n_dir = os.path.join(root_dir, "webui", "i18n")
config_file = os.path.join(root_dir, "webui", ".streamlit", "webui.toml")
system_locale = utils.get_system_locale()


if "video_subject" not in st.session_state:
    st.session_state["video_subject"] = ""
if "video_script" not in st.session_state:
    st.session_state["video_script"] = ""
if "video_terms" not in st.session_state:
    st.session_state["video_terms"] = ""
if "video_script_prompt" not in st.session_state:
    st.session_state["video_script_prompt"] = ""
if "custom_system_prompt" not in st.session_state:
    st.session_state["custom_system_prompt"] = llm.DEFAULT_SCRIPT_SYSTEM_PROMPT
if "use_custom_system_prompt" not in st.session_state:
    st.session_state["use_custom_system_prompt"] = False
if "ui_language" not in st.session_state:
    st.session_state["ui_language"] = config.ui.get("language", system_locale)
if "local_video_materials" not in st.session_state:
    # 记住用户最近一次已经落盘的本地素材，避免二次生成时丢失素材列表。
    st.session_state["local_video_materials"] = []
if "generation_in_progress" not in st.session_state:
    st.session_state["generation_in_progress"] = False
if "_config_snapshot" not in st.session_state:
    st.session_state["_config_snapshot"] = get_config_snapshot()

# 鍔犺浇璇█鏂囦欢
locales = utils.load_locales(i18n_dir)

# 鍒涘缓涓€涓《閮ㄦ爮锛屽寘鍚爣棰樺拰璇█閫夋嫨
title_col, lang_col = st.columns([3, 1])

with title_col:
    st.title(f"鐧芥辰蹇€熸贩鍓棰?v{config.project_version}")

with lang_col:
    display_languages = []
    selected_index = 0
    for i, code in enumerate(locales.keys()):
        display_languages.append(f"{code} - {locales[code].get('Language')}")
        if code == st.session_state.get("ui_language", ""):
            selected_index = i

    selected_language = st.selectbox(
        "Language / 璇█",
        options=display_languages,
        index=selected_index,
        key="top_language_selector",
        label_visibility="collapsed",
    )
    if selected_language:
        code = selected_language.split(" - ")[0].strip()
        st.session_state["ui_language"] = code
        config.ui["language"] = code

support_locales = [
    "zh-CN",
    "zh-HK",
    "zh-TW",
    "de-DE",
    "en-US",
    "fr-FR",
    "ru-RU",
    "vi-VN",
    "th-TH",
    "tr-TR",
]


@st.cache_data(show_spinner=False)
def get_all_fonts():
    fonts = []
    for root, dirs, files in os.walk(font_dir):
        for file in files:
            if file.endswith(".ttf") or file.endswith(".ttc"):
                fonts.append(file)
    fonts.sort()
    return fonts


@st.cache_data(show_spinner=False)
def get_all_songs():
    songs = []
    for root, dirs, files in os.walk(song_dir):
        for file in files:
            if file.endswith(".mp3"):
                songs.append(file)
    return songs


def open_task_folder(task_id):
    try:
        # task_id 搴斿缁堟槸鏈嶅姟绔敓鎴愮殑 UUID銆傝繖閲屽厛鍋氭牸寮忔牎楠岋紝閬垮厤寮傚父鍊?
        # 閫氳繃璺緞鎷兼帴璁块棶浠诲姟鐩綍涔嬪鐨勪綅缃紝涔熼伩鍏嶅悗缁墦寮€鐩綍鏃惰Е鍙?
        # 骞冲彴 shell 瀵圭壒娈婂瓧绗︾殑瑙ｉ噴銆?
        normalized_task_id = str(UUID(str(task_id)))
        tasks_root = os.path.abspath(os.path.join(root_dir, "storage", "tasks"))
        path = os.path.abspath(os.path.join(tasks_root, normalized_task_id))

        # 鍗充娇 UUID 鏍￠獙閫氳繃锛屼篃鍐嶆纭鏈€缁堣矾寰勪粛鍦ㄤ换鍔℃牴鐩綍鍐咃紝閬垮厤
        # 鏈潵璋冪敤鏂硅皟鏁?task_id 鏉ユ簮鏃跺紩鍏ヨ矾寰勭┛瓒婇闄┿€?
        if not path.startswith(tasks_root + os.sep):
            logger.warning(f"invalid task folder path: {path}")
            return

        if os.path.isdir(path):
            webbrowser.open(f"file://{path}")
    except Exception as e:
        logger.error(e)


def scroll_to_bottom():
    js = """
    <script>
        console.log("scroll_to_bottom");
        function scroll(dummy_var_to_force_repeat_execution){
            var sections = parent.document.querySelectorAll('section.main');
            console.log(sections);
            for(let index = 0; index<sections.length; index++) {
                sections[index].scrollTop = sections[index].scrollHeight;
            }
        }
        scroll(1);
    </script>
    """
    st.components.v1.html(js, height=0, width=0)


def init_log():
    logger.remove()
    _lvl = "DEBUG"

    def format_record(record):
        # 鑾峰彇鏃ュ織璁板綍涓殑鏂囦欢鍏ㄨ矾寰?
        file_path = record["file"].path
        # 灏嗙粷瀵硅矾寰勮浆鎹负鐩稿浜庨」鐩牴鐩綍鐨勮矾寰?
        relative_path = os.path.relpath(file_path, root_dir)
        # 鏇存柊璁板綍涓殑鏂囦欢璺緞
        record["file"].path = f"./{relative_path}"
        # 杩斿洖淇敼鍚庣殑鏍煎紡瀛楃涓?
        # 鎮ㄥ彲浠ユ牴鎹渶瑕佽皟鏁磋繖閲岀殑鏍煎紡
        record["message"] = record["message"].replace(root_dir, ".")

        _format = (
            "<green>{time:%Y-%m-%d %H:%M:%S}</> | "
            + "<level>{level}</> | "
            + '"{file.path}:{line}":<blue> {function}</> '
            + "- <level>{message}</>"
            + "\n"
        )
        return _format

    logger.add(
        sys.stdout,
        level=_lvl,
        format=format_record,
        colorize=True,
    )


init_log()

locales = utils.load_locales(i18n_dir)


def tr(key):
    loc = locales.get(st.session_state["ui_language"], {})
    return loc.get("Translation", {}).get(key, key)

@st.cache_data(ttl=300, show_spinner=False)
def get_groq_model_ids(api_key: str, base_url: str) -> list[str]:
    if not api_key:
        return []

    normalized_base_url = (base_url or "https://api.groq.com/openai/v1").strip().rstrip("/")
    models_url = f"{normalized_base_url}/models"

    try:
        response = requests.get(
            models_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data", [])

        model_ids = []
        for item in data:
            if isinstance(item, dict):
                model_id = item.get("id")
                if isinstance(model_id, str) and model_id.strip():
                    model_ids.append(model_id.strip())

        return sorted(set(model_ids))
    except Exception as e:
        logger.warning(f"failed to fetch groq models: {e}")
        return []

# 鍒涘缓鍩虹璁剧疆鎶樺彔妗?
if not config.app.get("hide_config", False):
    with st.expander(tr("Basic Settings"), expanded=False):
        config_panels = st.columns(3)
        left_config_panel = config_panels[0]
        middle_config_panel = config_panels[1]
        right_config_panel = config_panels[2]

        # 宸︿晶闈㈡澘 - 鏃ュ織璁剧疆
        with left_config_panel:
            # 鏄惁闅愯棌閰嶇疆闈㈡澘
            hide_config = st.checkbox(
                tr("Hide Basic Settings"), value=config.app.get("hide_config", False)
            )
            config.app["hide_config"] = hide_config

            # 鏄惁绂佺敤鏃ュ織鏄剧ず
            hide_log = st.checkbox(
                tr("Hide Log"), value=config.ui.get("hide_log", False)
            )
            config.ui["hide_log"] = hide_log

        # 涓棿闈㈡澘 - LLM 璁剧疆

        with middle_config_panel:
            st.write(tr("LLM Settings"))
            # 涓嬫媺妗嗛渶瑕佸睍绀衡€淎IHubMix锛堟帹鑽愶級鈥濊繖绫婚潰鍚戠敤鎴风殑鏂囨锛?
            # 浣嗛厤缃枃浠跺拰鍚庣閫昏緫蹇呴』缁х画浣跨敤绋冲畾鐨勫皬鍐?provider id銆?
            # 鍥犳杩欓噷鏄惧紡缁存姢 display label 鍜?provider id 鐨勬槧灏勶紝閬垮厤
            # UI 鏂囨鍙樺寲姹℃煋 `config.app["llm_provider"]`銆?
            aihubmix_label = f"AIHubMix ({tr('Recommended')})"
            if config.ui.get("language") == "zh":
                aihubmix_label = "AIHubMix锛堟帹鑽愶級"
            llm_provider_options = [
                ("OpenAI", "openai"),
                (aihubmix_label, "aihubmix"),
                ("Moonshot", "moonshot"),
                ("Azure", "azure"),
                ("Qwen", "qwen"),
                ("DeepSeek", "deepseek"),
                ("ModelScope", "modelscope"),
                ("Gemini", "gemini"),
                ("Grok", "grok"),
                ("Groq", "groq"),
                ("Ollama", "ollama"),
                ("G4f", "g4f"),
                ("OneAPI", "oneapi"),
                ("Cloudflare", "cloudflare"),
                ("ERNIE", "ernie"),
                ("MiniMax", "minimax"),
                ("MiMo", "mimo"),
                ("Pollinations", "pollinations"),
                ("LiteLLM", "litellm"),
            ]
            llm_provider_labels = [label for label, _ in llm_provider_options]
            llm_provider_values = {
                label: provider_id for label, provider_id in llm_provider_options
            }
            saved_llm_provider = config.app.get("llm_provider", "openai").lower()
            saved_llm_provider_index = 0
            for i, (_, provider_id) in enumerate(llm_provider_options):
                if provider_id == saved_llm_provider:
                    saved_llm_provider_index = i
                    break

            llm_provider_label = st.selectbox(
                tr("LLM Provider"),
                options=llm_provider_labels,
                index=saved_llm_provider_index,
            )
            llm_helper = st.container()
            llm_provider = llm_provider_values[llm_provider_label]
            config.app["llm_provider"] = llm_provider

            llm_api_key = config.app.get(f"{llm_provider}_api_key", "")
            llm_secret_key = config.app.get(
                f"{llm_provider}_secret_key", ""
            )  # only for baidu ernie
            llm_base_url = config.app.get(f"{llm_provider}_base_url", "")
            llm_model_name = config.app.get(f"{llm_provider}_model_name", "")
            llm_account_id = config.app.get(f"{llm_provider}_account_id", "")

            tips = ""
            if llm_provider == "ollama":
                if not llm_model_name:
                    llm_model_name = "qwen:7b"
                if not llm_base_url:
                    llm_base_url = config.get_default_ollama_base_url()

                with llm_helper:
                    docker_hint = ""
                    if config.is_running_in_container():
                        docker_hint = "\n                            > 妫€娴嬪埌瀹瑰櫒鐜锛屾湭閰嶇疆 Base Url 鏃朵細榛樿浣跨敤 `http://host.docker.internal:11434/v1`\n"
                    tips = f"""
                            ##### Ollama閰嶇疆璇存槑
                            - **API Key**: 闅忎究濉啓锛屾瘮濡?123
                            - **Base Url**: 涓€鑸负 http://localhost:11434/v1
                                - 濡傛灉 `鐧芥辰蹇€熸贩鍓棰慲 鍜?`Ollama` **涓嶅湪鍚屼竴鍙版満鍣ㄤ笂**锛岄渶瑕佸～鍐?`Ollama` 鏈哄櫒鐨処P鍦板潃
                                - 濡傛灉 `鐧芥辰蹇€熸贩鍓棰慲 鏄?`Docker` 閮ㄧ讲锛屽缓璁～鍐?`http://host.docker.internal:11434/v1`{docker_hint}
                            - **Model Name**: 浣跨敤 `ollama list` 鏌ョ湅锛屾瘮濡?`qwen:7b`
                            """

            if llm_provider == "openai":
                if not llm_model_name:
                    llm_model_name = "gpt-3.5-turbo"
                with llm_helper:
                    tips = """
                            ##### OpenAI 閰嶇疆璇存槑
                            > 闇€瑕乂PN寮€鍚叏灞€娴侀噺妯″紡
                            - **API Key**: [鐐瑰嚮鍒板畼缃戠敵璇穄(https://platform.openai.com/api-keys)
                            - **Base Url**: 瀹樻柟 OpenAI 鍙暀绌猴紱濡傛灉浣跨敤 OpenAI 鍏煎渚涘簲鍟嗭紙渚嬪 OpenRouter锛夛紝璇峰～鍐欏搴旂殑鍏煎鎺ュ彛鍦板潃
                            - **Model Name**: 濉啓**鏈夋潈闄?*鐨勬ā鍨嬶紱濡傛灉浣跨敤鍏煎渚涘簲鍟嗭紝璇峰～鍐欒骞冲彴鏀寔鐨勬ā鍨?ID
                            """

            if llm_provider == "aihubmix":
                if not llm_model_name:
                    llm_model_name = "gpt-5.4-mini"
                if not llm_base_url:
                    llm_base_url = "https://aihubmix.com/v1"
                with llm_helper:
                    tips = """
                            ##### AIHubMix 閰嶇疆璇存槑
                            - **娉ㄥ唽閾炬帴**: [鐐瑰嚮娉ㄥ唽 AIHubMix](https://aihubmix.com/)
                            - **Base Url**: 棰勫～ https://aihubmix.com/v1
                            - **鎺ㄨ崘妯″瀷**: 榛樿 gpt-5.4-mini锛屼篃鍙互濉啓 AIHubMix 鏀寔鐨勫厤璐规ā鍨嬫垨鍏跺畠妯″瀷 ID

                            鎺ㄨ崘鐞嗙敱锛?
                            - **妯″瀷鍏?*: Claude銆丟PT銆丟emini銆丟rok銆丏eepSeek銆侀€氫箟绛?700+ 妯″瀷涓€绔欒鐩?
                            - **绋冲畾**: 鏃犻檺骞跺彂锛屾案杩滃湪绾匡紝闆嗙兢閮ㄧ讲浜庤胺姝屼簯锛岄暱鏈熶负浼楀鐭ュ悕搴旂敤鎻愪緵楂樺苟鍙戞湇鍔?
                            - **鑳藉姏瀹屾暣**: 鏂囨湰銆佸浘鐗囩敓鎴愩€佽棰戠敓鎴愩€乀TS銆丼TT銆佸悜閲忓祵鍏ャ€丷erank锛屽妯℃€佸満鏅叏鎼炲畾
                            - **璁¤垂閫忔槑**: 鎸夐噺浠樿垂锛屾棤浼氬憳鏃犲寘鏈堬紝鍏嶈垂妯″瀷鍙娇鐢?
                            """

            if llm_provider == "moonshot":
                if not llm_model_name:
                    llm_model_name = "moonshot-v1-8k"
                with llm_helper:
                    tips = """
                            ##### Moonshot 閰嶇疆璇存槑
                            - **API Key**: [鐐瑰嚮鍒板畼缃戠敵璇穄(https://platform.moonshot.cn/console/api-keys)
                            - **Base Url**: 鍥哄畾涓?https://api.moonshot.cn/v1
                            - **Model Name**: 姣斿 moonshot-v1-8k锛孾鐐瑰嚮鏌ョ湅妯″瀷鍒楄〃](https://platform.moonshot.cn/docs/intro#%E6%A8%A1%E5%9E%8B%E5%88%97%E8%A1%A8)
                            """
            if llm_provider == "oneapi":
                if not llm_model_name:
                    llm_model_name = (
                        "claude-3-5-sonnet-20240620"  # 榛樿妯″瀷锛屽彲浠ユ牴鎹渶瑕佽皟鏁?
                    )
                with llm_helper:
                    tips = """
                        ##### OneAPI 閰嶇疆璇存槑
                        - **API Key**: 濉啓鎮ㄧ殑 OneAPI 瀵嗛挜
                        - **Base Url**: 濉啓 OneAPI 鐨勫熀纭€ URL
                        - **Model Name**: 濉啓鎮ㄨ浣跨敤鐨勬ā鍨嬪悕绉帮紝渚嬪 claude-3-5-sonnet-20240620
                        """

            if llm_provider == "qwen":
                if not llm_model_name:
                    llm_model_name = "qwen-max"
                with llm_helper:
                    tips = """
                            ##### 閫氫箟鍗冮棶Qwen 閰嶇疆璇存槑
                            - **API Key**: [鐐瑰嚮鍒板畼缃戠敵璇穄(https://dashscope.console.aliyun.com/apiKey)
                            - **Base Url**: 鐣欑┖
                            - **Model Name**: 姣斿 qwen-max锛孾鐐瑰嚮鏌ョ湅妯″瀷鍒楄〃](https://help.aliyun.com/zh/dashscope/developer-reference/model-introduction#3ef6d0bcf91wy)
                            """

            if llm_provider == "g4f":
                if not llm_model_name:
                    llm_model_name = "gpt-3.5-turbo"
                with llm_helper:
                    tips = """
                            ##### gpt4free 閰嶇疆璇存槑
                            > [GitHub寮€婧愰」鐩甝(https://github.com/xtekky/gpt4free)锛屽彲浠ュ厤璐逛娇鐢℅PT妯″瀷锛屼絾鏄?*绋冲畾鎬ц緝宸?*
                            - **API Key**: 闅忎究濉啓锛屾瘮濡?123
                            - **Base Url**: 鐣欑┖
                            - **Model Name**: 姣斿 gpt-3.5-turbo锛孾鐐瑰嚮鏌ョ湅妯″瀷鍒楄〃](https://github.com/xtekky/gpt4free/blob/main/g4f/models.py#L308)
                            """
            if llm_provider == "azure":
                with llm_helper:
                    tips = """
                            ##### Azure 閰嶇疆璇存槑
                            > [鐐瑰嚮鏌ョ湅濡備綍閮ㄧ讲妯″瀷](https://learn.microsoft.com/zh-cn/azure/ai-services/openai/how-to/create-resource)
                            - **API Key**: [鐐瑰嚮鍒癆zure鍚庡彴鍒涘缓](https://portal.azure.com/#view/Microsoft_Azure_ProjectOxford/CognitiveServicesHub/~/OpenAI)
                            - **Base Url**: 鐣欑┖
                            - **Model Name**: 濉啓浣犲疄闄呯殑閮ㄧ讲鍚?
                            """

            if llm_provider == "gemini":
                if not llm_model_name:
                    llm_model_name = "gemini-1.0-pro"

                with llm_helper:
                    tips = """
                            ##### Gemini 閰嶇疆璇存槑
                            > 闇€瑕乂PN寮€鍚叏灞€娴侀噺妯″紡
                            - **API Key**: [鐐瑰嚮鍒板畼缃戠敵璇穄(https://ai.google.dev/)
                            - **Base Url**: 鐣欑┖
                            - **Model Name**: 姣斿 gemini-1.0-pro
                            """

            if llm_provider == "grok":
                if not llm_model_name:
                    llm_model_name = "grok-4.3"
                if not llm_base_url:
                    llm_base_url = "https://api.x.ai/v1"

                with llm_helper:
                    tips = """
                            ##### Grok 閰嶇疆璇存槑
                            - **API Key**: 濉啓鎮ㄧ殑 GrokAPI 瀵嗛挜
                            - **Base Url**: 濉啓 GrokAPI 鐨勫熀纭€ URL
                            - **Model Name**: 姣斿 grok-4.3
                            """

            if llm_provider == "groq":
                if not llm_model_name:
                    llm_model_name = "llama-3.3-70b-versatile"
                if not llm_base_url:
                    llm_base_url = "https://api.groq.com/openai/v1"

                with llm_helper:
                    tips = """
                            ##### Groq 閰嶇疆璇存槑
                            - **API Key**: [鐐瑰嚮鍒板畼缃戠敵璇穄(https://console.groq.com/keys)
                            - **Base Url**: 鍥哄畾涓?https://api.groq.com/openai/v1
                            - **Model Name**: 姣斿 llama-3.3-70b-versatile
                            """

            if llm_provider == "deepseek":
                if not llm_model_name:
                    llm_model_name = "deepseek-chat"
                if not llm_base_url:
                    llm_base_url = "https://api.deepseek.com"
                with llm_helper:
                    tips = """
                            ##### DeepSeek 閰嶇疆璇存槑
                            - **API Key**: [鐐瑰嚮鍒板畼缃戠敵璇穄(https://platform.deepseek.com/api_keys)
                            - **Base Url**: 鍥哄畾涓?https://api.deepseek.com
                            - **Model Name**: 鍥哄畾涓?deepseek-chat
                            """

            if llm_provider == "mimo":
                if not llm_model_name:
                    llm_model_name = "mimo-v2.5-pro"
                if not llm_base_url:
                    llm_base_url = "https://api.xiaomimimo.com/v1"
                with llm_helper:
                    tips = """
                            ##### Xiaomi MiMo 閰嶇疆璇存槑
                            - **API Key**: [鐐瑰嚮鍒板畼缃戠敵璇穄(https://platform.xiaomimimo.com/docs/zh-CN/quick-start/first-api-call)
                            - **Base Url**: 鍥哄畾涓?https://api.xiaomimimo.com/v1
                            - **Model Name**: 榛樿 mimo-v2.5-pro锛屼篃鍙互鎸夊畼鏂规枃妗ｅ～鍐欏叾瀹冨彲鐢ㄦā鍨?
                            """

            if llm_provider == "modelscope":
                if not llm_model_name:
                    llm_model_name = "Qwen/Qwen3-32B"
                if not llm_base_url:
                    llm_base_url = "https://api-inference.modelscope.cn/v1/"
                with llm_helper:
                    tips = """
                            ##### ModelScope 閰嶇疆璇存槑
                            - **API Key**: [鐐瑰嚮鍒板畼缃戠敵璇穄(https://modelscope.cn/docs/model-service/API-Inference/intro)
                            - **Base Url**: 鍥哄畾涓?https://api-inference.modelscope.cn/v1/
                            - **Model Name**: 姣斿 Qwen/Qwen3-32B锛孾鐐瑰嚮鏌ョ湅妯″瀷鍒楄〃](https://modelscope.cn/models?filter=inference_type&page=1)
                            """

            if llm_provider == "ernie":
                with llm_helper:
                    tips = """
                            ##### 鐧惧害鏂囧績涓€瑷€ 閰嶇疆璇存槑
                            - **API Key**: [鐐瑰嚮鍒板畼缃戠敵璇穄(https://console.bce.baidu.com/qianfan/ais/console/applicationConsole/application)
                            - **Secret Key**: [鐐瑰嚮鍒板畼缃戠敵璇穄(https://console.bce.baidu.com/qianfan/ais/console/applicationConsole/application)
                            - **Base Url**: 濉啓 **璇锋眰鍦板潃** [鐐瑰嚮鏌ョ湅鏂囨。](https://cloud.baidu.com/doc/WENXINWORKSHOP/s/jlil56u11#%E8%AF%B7%E6%B1%82%E8%AF%B4%E6%98%8E)
                            """

            if llm_provider == "pollinations":
                if not llm_model_name:
                    llm_model_name = "default"
                with llm_helper:
                    tips = """
                            ##### Pollinations AI Configuration
                            - **API Key**: Optional - Leave empty for public access
                            - **Base Url**: Default is https://text.pollinations.ai/openai
                            - **Model Name**: Use 'openai-fast' or specify a model name
                            """

            if llm_provider == "litellm":
                if not llm_model_name:
                    llm_model_name = "openai/gpt-4o-mini"
                with llm_helper:
                    tips = """
                            ##### LiteLLM Configuration
                            > [LiteLLM](https://github.com/BerriAI/litellm) routes to 100+ LLM providers via a unified interface.
                            > Set your provider's API key as an env var: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `AWS_ACCESS_KEY_ID`, etc.
                            - **Model Name**: LiteLLM format 鈥?`openai/gpt-4o`, `anthropic/claude-sonnet-4-20250514`, `bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0`, `gemini/gemini-2.5-flash`. See [full provider list](https://docs.litellm.ai/docs/providers)
                            """

            if tips and config.ui["language"] == "zh":
                # AIHubMix 鑷韩灏辨槸 OpenAI-compatible 鑱氬悎骞冲彴锛涚敤鎴蜂富鍔ㄩ€夋嫨
                # 璇?provider 鏃讹紝鍐嶆樉绀?DeepSeek/Moonshot 鐨勯€氱敤鎺ㄨ崘浼氶€犳垚
                # 淇℃伅骞叉壈锛屼篃涓嶅埄浜庝繚鎸佸悎浣滃叆鍙ｇ殑杞婚噺銆佹竻鏅般€?
                if llm_provider != "aihubmix":
                    st.warning(
                        "涓浗鐢ㄦ埛寤鸿浣跨敤 **DeepSeek** 鎴?**Moonshot** 浣滀负澶фā鍨嬫彁渚涘晢\n- 鍥藉唴鍙洿鎺ヨ闂紝涓嶉渶瑕乂PN \n- 娉ㄥ唽灏遍€侀搴︼紝鍩烘湰澶熺敤"
                    )
                st.info(tips)

            st_llm_api_key = st.text_input(
                tr("API Key"), value=llm_api_key, type="password"
            )
            st_llm_base_url = st.text_input(tr("Base Url"), value=llm_base_url)
            st_llm_model_name = ""
            if llm_provider != "ernie":
                if llm_provider == "groq":
                    effective_api_key = st_llm_api_key or llm_api_key
                    effective_base_url = st_llm_base_url or llm_base_url
                    groq_models = get_groq_model_ids(
                        api_key=effective_api_key,
                        base_url=effective_base_url,
                    )

                    if groq_models:
                        selected_index = 0
                        if llm_model_name in groq_models:
                            selected_index = groq_models.index(llm_model_name)

                        st_llm_model_name = st.selectbox(
                            tr("Model Name"),
                            options=groq_models,
                            index=selected_index,
                            key="groq_model_name_select",
                        )
                    else:
                        st_llm_model_name = st.text_input(
                            tr("Model Name"),
                            value=llm_model_name,
                            key="groq_model_name_input",
                        )
                        if effective_api_key:
                            st.caption(
                                "Unable to load Groq model list right now. You can still enter a model name manually."
                            )
                        else:
                            st.caption(
                                "Add a Groq API key to load available models automatically."
                            )
                else:
                    st_llm_model_name = st.text_input(
                        tr("Model Name"),
                        value=llm_model_name,
                        key=f"{llm_provider}_model_name_input",
                    )
                if st_llm_model_name:
                    config.app[f"{llm_provider}_model_name"] = st_llm_model_name
            else:
                st_llm_model_name = None

            if st_llm_api_key:
                config.app[f"{llm_provider}_api_key"] = st_llm_api_key
            if st_llm_base_url:
                config.app[f"{llm_provider}_base_url"] = st_llm_base_url
            if st_llm_model_name:
                config.app[f"{llm_provider}_model_name"] = st_llm_model_name
            if llm_provider == "ernie":
                st_llm_secret_key = st.text_input(
                    tr("Secret Key"), value=llm_secret_key, type="password"
                )
                config.app[f"{llm_provider}_secret_key"] = st_llm_secret_key

            if llm_provider == "cloudflare":
                st_llm_account_id = st.text_input(
                    tr("Account ID"), value=llm_account_id
                )
                if st_llm_account_id:
                    config.app[f"{llm_provider}_account_id"] = st_llm_account_id

        # 鍙充晶闈㈡澘 - API 瀵嗛挜璁剧疆
        with right_config_panel:

            def get_keys_from_config(cfg_key):
                api_keys = config.app.get(cfg_key, [])
                if isinstance(api_keys, str):
                    api_keys = [api_keys]
                api_key = ", ".join(api_keys)
                return api_key

            def save_keys_to_config(cfg_key, value):
                value = value.replace(" ", "")
                if value:
                    config.app[cfg_key] = value.split(",")

            st.write(tr("Video Source Settings"))

            pexels_api_key = get_keys_from_config("pexels_api_keys")
            pexels_api_key = st.text_input(
                tr("Pexels API Key"), value=pexels_api_key, type="password"
            )
            save_keys_to_config("pexels_api_keys", pexels_api_key)

            pixabay_api_key = get_keys_from_config("pixabay_api_keys")
            pixabay_api_key = st.text_input(
                tr("Pixabay API Key"), value=pixabay_api_key, type="password"
            )
            save_keys_to_config("pixabay_api_keys", pixabay_api_key)

llm_provider = config.app.get("llm_provider", "").lower()
panel = st.columns(3)
left_panel = panel[0]
middle_panel = panel[1]
right_panel = panel[2]

params = VideoParams(video_subject="")
uploaded_files = []
uploaded_audio_file = None
uploaded_voice_reference_file = None
custom_audio_file_types = ["mp3", "wav", "m4a", "aac", "flac", "ogg"]

with left_panel:
    with st.container(border=True):
        st.write(tr("Video Script Settings"))
        params.video_subject = st.text_input(
            tr("Video Subject"),
            key="video_subject",
        ).strip()

        video_languages = [
            (tr("Auto Detect"), ""),
        ]
        for code in support_locales:
            video_languages.append((code, code))

        selected_index = st.selectbox(
            tr("Script Language"),
            index=0,
            options=range(
                len(video_languages)
            ),  # Use the index as the internal option value
            format_func=lambda x: video_languages[x][
                0
            ],  # The label is displayed to the user
        )
        params.video_language = video_languages[selected_index][1]

        with st.expander(tr("Advanced Script Settings"), expanded=False):
            params.paragraph_number = st.slider(
                tr("Script Paragraph Number"),
                min_value=llm.MIN_SCRIPT_PARAGRAPH_NUMBER,
                max_value=llm.MAX_SCRIPT_PARAGRAPH_NUMBER,
                value=st.session_state.get("paragraph_number_input", 1),
                key="paragraph_number_input",
            )
            params.video_script_prompt = st.text_area(
                tr("Custom Script Requirements"),
                height=100,
                max_chars=llm.MAX_SCRIPT_PROMPT_LENGTH,
                placeholder=tr("Custom Script Requirements Placeholder"),
                key="video_script_prompt",
            ).strip()

            use_custom_system_prompt = st.checkbox(
                tr("Use Custom System Prompt"),
                help=tr("Use Custom System Prompt Help"),
                key="use_custom_system_prompt",
            )

            if use_custom_system_prompt:
                custom_system_prompt = st.text_area(
                    tr("Custom System Prompt"),
                    height=240,
                    max_chars=llm.MAX_SCRIPT_SYSTEM_PROMPT_LENGTH,
                    key="custom_system_prompt",
                ).strip()
                params.custom_system_prompt = custom_system_prompt
            else:
                params.custom_system_prompt = ""

        if st.button(
            tr("Generate Video Script and Keywords"), key="auto_generate_script"
        ):
            with st.spinner(tr("Generating Video Script and Keywords")):
                script = llm.generate_script(
                    video_subject=params.video_subject,
                    language=params.video_language,
                    paragraph_number=params.paragraph_number,
                    video_script_prompt=params.video_script_prompt,
                    custom_system_prompt=params.custom_system_prompt,
                )
                terms = llm.generate_terms(params.video_subject, script)
                if "Error: " in script:
                    st.error(tr(script))
                elif "Error: " in terms:
                    st.error(tr(terms))
                else:
                    st.session_state["video_script"] = script
                    st.session_state["video_terms"] = ", ".join(terms)
        params.video_script = st.text_area(
            tr("Video Script"), value=st.session_state["video_script"], height=280
        )
        if st.button(tr("Generate Video Keywords"), key="auto_generate_terms"):
            if not params.video_script:
                st.error(tr("Please Enter the Video Subject"))
                st.stop()

            with st.spinner(tr("Generating Video Keywords")):
                terms = llm.generate_terms(params.video_subject, params.video_script)
                if "Error: " in terms:
                    st.error(tr(terms))
                else:
                    st.session_state["video_terms"] = ", ".join(terms)

        params.video_terms = st.text_area(
            tr("Video Keywords"), value=st.session_state["video_terms"]
        )

with middle_panel:
    with st.container(border=True):
        st.write(tr("Video Settings"))
        video_concat_modes = [
            (tr("Sequential"), "sequential"),
            (tr("Random"), "random"),
        ]
        video_sources = [
            (tr("Pexels"), "pexels"),
            (tr("Pixabay"), "pixabay"),
            (tr("Local file"), "local"),
            (tr("TikTok"), "douyin"),
            (tr("Bilibili"), "bilibili"),
            (tr("Xiaohongshu"), "xiaohongshu"),
        ]

        saved_video_source_name = config.app.get("video_source", "pexels")
        saved_video_source_index = [v[1] for v in video_sources].index(
            saved_video_source_name
        )

        selected_index = st.selectbox(
            tr("Video Source"),
            options=range(len(video_sources)),
            format_func=lambda x: video_sources[x][0],
            index=saved_video_source_index,
        )
        params.video_source = video_sources[selected_index][1]
        config.app["video_source"] = params.video_source

        if params.video_source == "local":
            # Streamlit 鐨勬枃浠剁被鍨嬫牎楠屽鎵╁睍鍚嶅ぇ灏忓啓鏁忔劅锛岃繖閲屽悓鏃舵斁琛屽ぇ灏忓啓涓ょ褰㈠紡銆?
            local_file_types = ["mp4", "mov", "avi", "flv", "mkv", "jpg", "jpeg", "png"]
            uploaded_files = st.file_uploader(
                tr("Upload Local Files"),
                type=local_file_types + [file_type.upper() for file_type in local_file_types],
                accept_multiple_files=True,
            )

        selected_index = st.selectbox(
            tr("Video Concat Mode"),
            index=1,
            options=range(
                len(video_concat_modes)
            ),  # Use the index as the internal option value
            format_func=lambda x: video_concat_modes[x][
                0
            ],  # The label is displayed to the user
        )
        params.video_concat_mode = VideoConcatMode(
            video_concat_modes[selected_index][1]
        )

        # 瑙嗛杞満妯″紡
        video_transition_modes = [
            (tr("None"), VideoTransitionMode.none.value),
            (tr("Shuffle"), VideoTransitionMode.shuffle.value),
            (tr("FadeIn"), VideoTransitionMode.fade_in.value),
            (tr("FadeOut"), VideoTransitionMode.fade_out.value),
            (tr("SlideIn"), VideoTransitionMode.slide_in.value),
            (tr("SlideOut"), VideoTransitionMode.slide_out.value),
        ]
        selected_index = st.selectbox(
            tr("Video Transition Mode"),
            options=range(len(video_transition_modes)),
            format_func=lambda x: video_transition_modes[x][0],
            index=0,
        )
        params.video_transition_mode = VideoTransitionMode(
            video_transition_modes[selected_index][1]
        )

        video_aspect_ratios = [
            (tr("Portrait"), VideoAspect.portrait.value),
            (tr("Landscape"), VideoAspect.landscape.value),
        ]
        selected_index = st.selectbox(
            tr("Video Ratio"),
            options=range(
                len(video_aspect_ratios)
            ),  # Use the index as the internal option value
            format_func=lambda x: video_aspect_ratios[x][
                0
            ],  # The label is displayed to the user
        )
        params.video_aspect = VideoAspect(video_aspect_ratios[selected_index][1])

        params.video_clip_duration = st.selectbox(
            tr("Clip Duration"), options=[2, 3, 4, 5, 6, 7, 8, 9, 10], index=1
        )
        params.video_count = st.selectbox(
            tr("Number of Videos Generated Simultaneously"),
            options=[1, 2, 3, 4, 5],
            index=0,
        )

        with st.expander(tr("Advanced Video Settings"), expanded=False):
            video_codec_options = [
                ("libx264 (CPU)", "libx264"),
                ("NVIDIA NVENC (h264_nvenc)", "h264_nvenc"),
                ("AMD AMF (h264_amf)", "h264_amf"),
                ("Intel QSV (h264_qsv)", "h264_qsv"),
                ("Windows MediaFoundation (h264_mf)", "h264_mf"),
                ("macOS VideoToolbox (h264_videotoolbox)", "h264_videotoolbox"),
            ]
            saved_video_codec = config.app.get("video_codec", "libx264")
            saved_video_codec_values = [item[1] for item in video_codec_options]
            if saved_video_codec not in saved_video_codec_values:
                saved_video_codec = "libx264"
            selected_codec_index = saved_video_codec_values.index(saved_video_codec)
            selected_codec_index = st.selectbox(
                tr("Video Encoder"),
                options=range(len(video_codec_options)),
                index=selected_codec_index,
                format_func=lambda x: video_codec_options[x][0],
                help=tr("Video Encoder Help"),
            )
            config.app["video_codec"] = video_codec_options[selected_codec_index][1]
    with st.container(border=True):
        st.write(tr("Audio Settings"))

        # 娣诲姞TTS鏈嶅姟鍣ㄩ€夋嫨涓嬫媺妗?
        tts_servers = [
            ("voxcpm-tts", "VoxCPM 声音克隆"),
        ]

        # 鑾峰彇淇濆瓨鐨凾TS鏈嶅姟鍣紝榛樿涓簐1
        saved_tts_server = config.ui.get("tts_server", "voxcpm-tts")
        saved_tts_server_index = 0
        for i, (server_value, _) in enumerate(tts_servers):
            if server_value == saved_tts_server:
                saved_tts_server_index = i
                break

        selected_tts_server_index = st.selectbox(
            tr("TTS Servers"),
            options=range(len(tts_servers)),
            format_func=lambda x: tts_servers[x][1],
            index=saved_tts_server_index,
        )

        selected_tts_server = tts_servers[selected_tts_server_index][0]
        config.ui["tts_server"] = selected_tts_server

        friendly_names = {
            voice_name: voice.get_voxcpm_voice_label(voice_name)
            for voice_name in voice.get_voxcpm_voices()
        }
        saved_voice_name = config.ui.get("voice_name", voice.VOXCPM_VOICE_NAME)
        if saved_voice_name not in friendly_names:
            saved_voice_name = voice.VOXCPM_VOICE_NAME
        voice_options = list(friendly_names.keys())
        selected_voice_index = st.selectbox(
            tr("Speech Synthesis"),
            options=range(len(voice_options)),
            index=voice_options.index(saved_voice_name),
            format_func=lambda x: friendly_names[voice_options[x]],
        )
        voice_name = voice_options[selected_voice_index]
        params.voice_name = voice_name
        config.ui["voice_name"] = voice_name

        uploaded_voice_reference_file = st.file_uploader(
            "声音克隆参考音频",
            type=custom_audio_file_types
            + [file_type.upper() for file_type in custom_audio_file_types],
            accept_multiple_files=False,
            key="voxcpm_reference_audio_uploader",
            help="这里上传的是克隆参考音频，不会替代最终旁白。",
        )
        if uploaded_voice_reference_file:
            st.audio(uploaded_voice_reference_file, format="audio/mp3")
        if voice_name == voice.VOXCPM_VOICE_NAME:
            st.caption("VoxCPM 已作为内置语音克隆引擎使用。上传参考音频后会按该音色克隆，不依赖本地网址服务。")
        else:
            st.caption("VoxCPM 已作为内置语音克隆引擎使用。当前音色会通过内置风格指令生成，也可以上传参考音频进一步克隆。")

        params.voice_volume = st.selectbox(
            tr("Speech Volume"),
            options=[0.6, 0.8, 1.0, 1.2, 1.5, 2.0, 3.0, 4.0, 5.0],
            index=2,
        )

        params.voice_rate = st.selectbox(
            tr("Speech Rate"),
            options=[0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5, 1.8, 2.0],
            index=2,
        )

        uploaded_audio_file = st.file_uploader(
            tr("Custom Audio File"),
            type=custom_audio_file_types
            + [file_type.upper() for file_type in custom_audio_file_types],
            accept_multiple_files=False,
            key="custom_audio_file_uploader",
        )
        if uploaded_audio_file:
            st.audio(uploaded_audio_file, format="audio/mp3")
            st.info(
                tr(
                    "Custom audio will be used directly. TTS synthesis will be skipped for this task."
                )
            )

        bgm_options = [
            (tr("No Background Music"), ""),
            (tr("Random Background Music"), "random"),
            (tr("Custom Background Music"), "custom"),
        ]
        selected_index = st.selectbox(
            tr("Background Music"),
            index=1,
            options=range(
                len(bgm_options)
            ),  # Use the index as the internal option value
            format_func=lambda x: bgm_options[x][
                0
            ],  # The label is displayed to the user
        )
        # Get the selected background music type
        params.bgm_type = bgm_options[selected_index][1]

        # Show or hide components based on the selection
        if params.bgm_type == "custom":
            custom_bgm_file = st.text_input(
                tr("Custom Background Music File"), key="custom_bgm_file_input"
            )
            if custom_bgm_file:
                # 杩欓噷涓嶇洿鎺ョ敤 os.path.exists 鍒ゆ柇锛屽洜涓虹敤鎴峰父瑙佽緭鍏ユ槸
                # output000.mp3锛岃繖涓枃浠跺悕闇€瑕佺敱鏈嶅姟灞傛槧灏勫埌 resource/songs
                # 鐩綍鍚庡啀鏍￠獙銆傛湇鍔″眰浼氱粺涓€闄愬埗鐩綍鍜屾枃浠剁被鍨嬶紝閬垮厤浠绘剰璺緞璇诲彇銆?
                params.bgm_file = custom_bgm_file.strip()
                # st.write(f":red[宸查€夋嫨鑷畾涔夎儗鏅煶涔怾锛?*{custom_bgm_file}**")
        params.bgm_volume = st.selectbox(
            tr("Background Music Volume"),
            options=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
            index=2,
        )

with right_panel:
    with st.container(border=True):
        st.write(tr("Subtitle Settings"))
        params.subtitle_enabled = st.checkbox(tr("Enable Subtitles"), value=True)
        font_names = get_all_fonts()
        saved_font_name = config.ui.get("font_name", "MicrosoftYaHeiBold.ttc")
        saved_font_name_index = 0
        if saved_font_name in font_names:
            saved_font_name_index = font_names.index(saved_font_name)
        params.font_name = st.selectbox(
            tr("Font"), font_names, index=saved_font_name_index
        )
        config.ui["font_name"] = params.font_name

        subtitle_positions = [
            (tr("Top"), "top"),
            (tr("Center"), "center"),
            (tr("Bottom"), "bottom"),
            (tr("Custom"), "custom"),
        ]
        saved_subtitle_position = config.ui.get("subtitle_position", "custom")
        saved_position_index = 3
        for i, (_, pos_value) in enumerate(subtitle_positions):
            if pos_value == saved_subtitle_position:
                saved_position_index = i
                break
        selected_index = st.selectbox(
            tr("Position"),
            index=saved_position_index,
            options=range(len(subtitle_positions)),
            format_func=lambda x: subtitle_positions[x][0],
        )
        params.subtitle_position = subtitle_positions[selected_index][1]
        config.ui["subtitle_position"] = params.subtitle_position

        if params.subtitle_position == "custom":
            saved_custom_position = config.ui.get("custom_position", 75.0)
            custom_position = st.text_input(
                tr("Custom Position (% from top)"),
                value=str(saved_custom_position),
                key="custom_position_input",
            )
            try:
                params.custom_position = float(custom_position)
                if params.custom_position < 0 or params.custom_position > 100:
                    st.error(tr("Please enter a value between 0 and 100"))
                else:
                    config.ui["custom_position"] = params.custom_position
            except ValueError:
                st.error(tr("Please enter a valid number"))

        font_cols = st.columns([0.3, 0.7])
        with font_cols[0]:
            saved_text_fore_color = config.ui.get("text_fore_color", "#FFFFFF")
            params.text_fore_color = st.color_picker(
                tr("Font Color"), saved_text_fore_color
            )
            config.ui["text_fore_color"] = params.text_fore_color

        with font_cols[1]:
            saved_font_size = config.ui.get("font_size", 60)
            params.font_size = st.slider(tr("Font Size"), 30, 100, saved_font_size)
            config.ui["font_size"] = params.font_size

        stroke_cols = st.columns([0.3, 0.7])
        with stroke_cols[0]:
            params.stroke_color = st.color_picker(tr("Stroke Color"), "#000000")
        with stroke_cols[1]:
            params.stroke_width = st.slider(tr("Stroke Width"), 0.0, 10.0, 1.5)

        subtitle_bg_cols = st.columns([0.4, 0.6])
        saved_subtitle_background_enabled = config.ui.get(
            "subtitle_background_enabled", True
        )
        with subtitle_bg_cols[0]:
            subtitle_background_enabled = st.checkbox(
                tr("Enable Subtitle Background"),
                value=saved_subtitle_background_enabled,
            )
        config.ui["subtitle_background_enabled"] = subtitle_background_enabled
        if subtitle_background_enabled:
            with subtitle_bg_cols[1]:
                saved_subtitle_background_color = config.ui.get(
                    "subtitle_background_color", "#000000"
                )
                params.text_background_color = st.color_picker(
                    tr("Subtitle Background Color"),
                    saved_subtitle_background_color,
                )
                config.ui["subtitle_background_color"] = params.text_background_color
        else:
            params.text_background_color = False

        saved_rounded_subtitle_background = config.ui.get(
            "rounded_subtitle_background", False
        )
        # 鑳屾櫙鍏抽棴鏃讹紝鍦嗚鑳屾櫙娌℃湁鍙覆鏌撶殑搴曡壊銆傝繖閲岀鐢ㄦ帶浠跺苟淇濈暀鍘熼厤缃紝
        # 鐢ㄦ埛涓嬫閲嶆柊寮€鍚瓧骞曡儗鏅悗锛屽彲浠ョ户缁娇鐢ㄤ箣鍓嶄繚瀛樼殑鍦嗚鍋忓ソ銆?
        params.rounded_subtitle_background = st.checkbox(
            tr("Rounded Subtitle Background"),
            value=(
                saved_rounded_subtitle_background
                if subtitle_background_enabled
                else False
            ),
            help=tr("Rounded Subtitle Background Help"),
            disabled=not subtitle_background_enabled,
        )
        if subtitle_background_enabled:
            config.ui["rounded_subtitle_background"] = (
                params.rounded_subtitle_background
            )
    with st.expander(tr("Click to show API Key management"), expanded=False):
        st.subheader(tr("Manage Pexels and Pixabay API Keys"))

        col1, col2 = st.tabs([tr("Pexels API Keys"), tr("Pixabay API Keys")])

        with col1:
            st.subheader(tr("Pexels API Keys"))
            if config.app["pexels_api_keys"]:
                st.write(tr("Current Keys:"))
                for key in config.app["pexels_api_keys"]:
                    st.code(key)
            else:
                st.info(tr("No Pexels API Keys currently"))

            new_key = st.text_input(tr("Add Pexels API Key"), key="pexels_new_key")
            if st.button(tr("Add Pexels API Key")):
                if new_key and new_key not in config.app["pexels_api_keys"]:
                    config.app["pexels_api_keys"].append(new_key)
                    save_config_if_changed(force=True)
                    st.success(tr("Pexels API Key added successfully"))
                elif new_key in config.app["pexels_api_keys"]:
                    st.warning(tr("This API Key already exists"))
                else:
                    st.error(tr("Please enter a valid API Key"))

            if config.app["pexels_api_keys"]:
                delete_key = st.selectbox(
                    tr("Select Pexels API Key to delete"), config.app["pexels_api_keys"], key="pexels_delete_key"
                )
                if st.button(tr("Delete Selected Pexels API Key")):
                    config.app["pexels_api_keys"].remove(delete_key)
                    save_config_if_changed(force=True)
                    st.success(tr("Pexels API Key deleted successfully"))

        with col2:
            st.subheader(tr("Pixabay API Keys"))

            if config.app["pixabay_api_keys"]:
                st.write(tr("Current Keys:"))
                for key in config.app["pixabay_api_keys"]:
                    st.code(key)
            else:
                st.info(tr("No Pixabay API Keys currently"))

            new_key = st.text_input(tr("Add Pixabay API Key"), key="pixabay_new_key")
            if st.button(tr("Add Pixabay API Key")):
                if new_key and new_key not in config.app["pixabay_api_keys"]:
                    config.app["pixabay_api_keys"].append(new_key)
                    save_config_if_changed(force=True)
                    st.success(tr("Pixabay API Key added successfully"))
                elif new_key in config.app["pixabay_api_keys"]:
                    st.warning(tr("This API Key already exists"))
                else:
                    st.error(tr("Please enter a valid API Key"))

            if config.app["pixabay_api_keys"]:
                delete_key = st.selectbox(
                    tr("Select Pixabay API Key to delete"), config.app["pixabay_api_keys"], key="pixabay_delete_key"
                )
                if st.button(tr("Delete Selected Pixabay API Key")):
                    config.app["pixabay_api_keys"].remove(delete_key)
                    save_config_if_changed(force=True)
                    st.success(tr("Pixabay API Key deleted successfully"))

start_button = st.button(
    tr("Generate Video"),
    use_container_width=True,
    type="primary",
    disabled=st.session_state["generation_in_progress"],
)
if start_button:
    st.session_state["generation_in_progress"] = True
    save_config_if_changed(force=True)
    task_id = str(uuid4())
    if not params.video_subject and not params.video_script:
        st.error(tr("Video Script and Subject Cannot Both Be Empty"))
        st.session_state["generation_in_progress"] = False
        scroll_to_bottom()
        st.stop()

    if params.video_source not in ["pexels", "pixabay", "local"]:
        st.error(tr("Please Select a Valid Video Source"))
        st.session_state["generation_in_progress"] = False
        scroll_to_bottom()
        st.stop()

    if params.video_source == "pexels" and not config.app.get("pexels_api_keys", ""):
        st.error(tr("Please Enter the Pexels API Key"))
        st.session_state["generation_in_progress"] = False
        scroll_to_bottom()
        st.stop()

    if params.video_source == "pixabay" and not config.app.get("pixabay_api_keys", ""):
        st.error(tr("Please Enter the Pixabay API Key"))
        st.session_state["generation_in_progress"] = False
        scroll_to_bottom()
        st.stop()

    if uploaded_audio_file:
        task_dir = utils.task_dir(task_id)
        # 涓婁紶鏂囦欢鍚嶆潵鑷祻瑙堝櫒锛屼笉鑳界洿鎺ユ嫾鍒扮鐩樿矾寰勯噷锛涜繖閲屽彧淇濈暀鎵╁睍鍚嶏紝
        # 骞朵娇鐢ㄥ浐瀹氭枃浠跺悕淇濆瓨鍒板綋鍓嶄换鍔＄洰褰曪紝閬垮厤璺緞绌胯秺鎴栫壒娈婂瓧绗﹂棶棰樸€?
        _, audio_ext = os.path.splitext(os.path.basename(uploaded_audio_file.name))
        audio_ext = audio_ext.lower() or ".mp3"
        custom_audio_path = os.path.join(task_dir, f"custom-audio{audio_ext}")
        with open(custom_audio_path, "wb") as f:
            f.write(uploaded_audio_file.getbuffer())
        params.custom_audio_file = custom_audio_path

    if uploaded_voice_reference_file:
        task_dir = utils.task_dir(task_id)
        _, audio_ext = os.path.splitext(
            os.path.basename(uploaded_voice_reference_file.name)
        )
        audio_ext = audio_ext.lower() or ".wav"
        reference_audio_path = os.path.join(task_dir, f"voice-reference{audio_ext}")
        with open(reference_audio_path, "wb") as f:
            f.write(uploaded_voice_reference_file.getbuffer())
        params.voice_reference_audio_file = reference_audio_path

    if uploaded_files:
        local_videos_dir = utils.storage_dir("local_videos", create=True)
        # 姣忔閲嶆柊涓婁紶鏃堕兘浠ユ湰娆￠€夋嫨鐨勭礌鏉愪负鍑嗭紝閬垮厤鏃х礌鏉愪笉鏂噸澶嶈拷鍔犮€?
        params.video_materials = []
        persisted_local_materials = []
        for file in uploaded_files:
            file_path = os.path.join(local_videos_dir, f"{file.file_id}_{file.name}")
            with open(file_path, "wb") as f:
                f.write(file.getbuffer())
                m = MaterialInfo()
                m.provider = "local"
                m.url = file_path
                params.video_materials.append(m)
                persisted_local_materials.append(
                    {
                        "provider": m.provider,
                        "url": m.url,
                        "duration": m.duration,
                    }
                )
        # 灏嗗凡涓婁紶骞朵繚瀛樺埌鏈湴鐨勮棰戠礌鏉愬啓鍏ヤ細璇濓紝渚涘悗缁彧鏀规枃妗堟椂鐩存帴澶嶇敤銆?
        st.session_state["local_video_materials"] = persisted_local_materials
    elif params.video_source == "local" and st.session_state["local_video_materials"]:
        # 褰撶敤鎴锋病鏈夐噸鏂颁笂浼犳枃浠舵椂锛屽鐢ㄦ渶杩戜竴娆″凡缁忎繚瀛樺埌纾佺洏鐨勬湰鍦扮礌鏉愬垪琛ㄣ€?
        params.video_materials = []
        for material in st.session_state["local_video_materials"]:
            m = MaterialInfo()
            m.provider = material.get("provider", "local")
            m.url = material.get("url", "")
            m.duration = material.get("duration", 0)
            if m.url:
                params.video_materials.append(m)

    log_container = st.empty()
    log_records = []

    def log_received(msg):
        if config.ui["hide_log"]:
            return
        with log_container:
            log_records.append(msg)
            st.caption("鐢熸垚杩涘害")
            st.code("\n".join(log_records[-6:]))
            with st.expander("瀹屾暣鏃ュ織", expanded=False):
                st.code("\n".join(log_records[-400:]))

    log_handler_id = logger.add(log_received)

    st.toast(tr("Generating Video"))
    logger.info(tr("Start Generating Video"))
    logger.info(
        "generation params: "
        f"subject={params.video_subject!r}, "
        f"aspect={params.video_aspect}, "
        f"source={params.video_source}, "
        f"tts={params.voice_name}, "
        f"clip_duration={params.video_clip_duration}, "
        f"count={params.video_count}"
    )
    scroll_to_bottom()

    try:
        with st.status(tr("Generating Video"), expanded=False):
            from app.services import task as tm

            result = tm.start(task_id=task_id, params=params)
    except Exception as e:
        logger.exception(f"video generation crashed: {str(e)}")
        result = None
    finally:
        try:
            logger.remove(log_handler_id)
        except Exception:
            pass

    if not result or "videos" not in result:
        st.error(tr("Video Generation Failed"))
        logger.error(tr("Video Generation Failed"))
        st.session_state["generation_in_progress"] = False
        scroll_to_bottom()
        st.stop()

    video_files = result.get("videos", [])
    st.success(tr("Video Generation Completed"))
    try:
        if video_files:
            player_cols = st.columns(len(video_files) * 2 + 1)
            for i, url in enumerate(video_files):
                player_cols[i * 2 + 1].video(url)
    except Exception:
        pass

    open_task_folder(task_id)
    logger.info(tr("Video Generation Completed"))
    st.session_state["generation_in_progress"] = False
    scroll_to_bottom()

save_config_if_changed()
