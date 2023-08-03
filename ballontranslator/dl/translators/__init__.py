import urllib.request
from urllib3.exceptions import ConnectTimeoutError
from ordered_set import OrderedSet
from typing import Dict, List, Union, Set, Callable
import time, requests, re, uuid, base64, hmac, functools, json, deepl
import ctranslate2, sentencepiece as spm
from .exceptions import InvalidSourceOrTargetLanguage, TranslatorSetupFailure, MissingTranslatorParams, TranslatorNotValid
from ..textdetector.textblock import TextBlock
from ..moduleparamparser import ModuleParamParser
from utils.registry import Registry
from utils.io_utils import text_is_empty
from .hooks import chs2cht
import random
import hashlib
TRANSLATORS = Registry('translators')
register_translator = TRANSLATORS.register_module
PROXY = urllib.request.getproxies()
LANGMAP_GLOBAL = {
    'Auto': '',
    '简体中文': '',
    '繁體中文': '',
    '日本語': '',
    'English': '',
    '한국어': '',
    'Tiếng Việt': '',
    'čeština': '',
    'Nederlands': '',
    'français': '',
    'Deutsch': '',
    'magyar nyelv': '',
    'italiano': '',
    'polski': '',
    'português': '',
    'limba română': '',
    'русский язык': '',
    'español': '',
    'Türk dili': ''        
}

SYSTEM_LANG = ''
SYSTEM_LANGMAP = {
    'zh-CN': '简体中文'        
}


def check_language_support(check_type: str = 'source'):
    
    def decorator(set_lang_method):
        @functools.wraps(set_lang_method)
        def wrapper(self, lang: str = ''):
            if check_type == 'source':
                supported_lang_list = self.supported_src_list
            else:
                supported_lang_list = self.supported_tgt_list
            if lang not in supported_lang_list:
                msg = '\n'.join(supported_lang_list)
                raise InvalidSourceOrTargetLanguage(f'Invalid {check_type}: {lang}\n', message=msg)
            return set_lang_method(self, lang)

        return wrapper

    return decorator


class TranslatorBase(ModuleParamParser):

    concate_text = True
    cht_require_convert = False
    
    
    def __init__(self,
                 lang_source: str, 
                 lang_target: str,
                 raise_unsupported_lang: bool = True,
                 **setup_params) -> None:
        super().__init__(**setup_params)
        self.name = next(
            (
                key
                for key in TRANSLATORS.module_dict
                if TRANSLATORS.module_dict[key] == self.__class__
            ),
            '',
        )
        self.textblk_break = '\n###\n'
        self.lang_source: str = lang_source
        self.lang_target: str = lang_target
        self.lang_map: Dict = LANGMAP_GLOBAL.copy()
        self.postprocess_hooks = OrderedSet()

        try:
            self.setup_translator()
        except Exception as e:
            if isinstance(e, MissingTranslatorParams):
                raise e
            else:
                raise TranslatorSetupFailure(e)

        self.valid_lang_list = [lang for lang in self.lang_map if self.lang_map[lang] != '']

        try:
            self.set_source(lang_source)
            self.set_target(lang_target)
        except InvalidSourceOrTargetLanguage as e:
            if raise_unsupported_lang:
                raise e
            lang_source = self.supported_src_list[0]
            lang_target = self.supported_tgt_list[0]
            self.set_source(lang_source)
            self.set_target(lang_target)

        if self.cht_require_convert:
            self.register_postprocess_hooks(self._chs2cht)

    def register_postprocess_hooks(self, callbacks: Union[List, Callable]):
        if callbacks is None:
            return
        if isinstance(callbacks, Callable):
            callbacks = [callbacks]
        for callback in callbacks:
            self.postprocess_hooks.add(callback)

    def _setup_translator(self):
        raise NotImplementedError

    def setup_translator(self):
        self._setup_translator()

    @check_language_support(check_type='source')
    def set_source(self, lang: str):
        self.lang_source = lang

    @check_language_support(check_type='target')
    def set_target(self, lang: str):
        self.lang_target = lang

    def _translate(self, text: Union[str, List]) -> Union[str, List]:
        raise NotImplementedError

    def translate(self, text: Union[str, List]) -> Union[str, List]:
        if text_is_empty(text):
            return text

        concate_text = isinstance(text, List) and self.concate_text
        text_source = self.textlist2text(text) if concate_text else text

        text_trans = self._translate(text_source)

        if text_trans is None:
            text_trans = [''] * len(text) if isinstance(text, List) else ''
        elif concate_text:
            text_trans = self.text2textlist(text_trans)

        if isinstance(text, List):
            assert len(text_trans) == len(text)
            for ii, t in enumerate(text_trans):
                for callback in self.postprocess_hooks:
                    text_trans[ii] = callback(t)
        else:
            for callback in self.postprocess_hooks:
                text_trans = callback(text_trans)

        return text_trans

    def textlist2text(self, text_list: List[str]) -> str:
        # some translators automatically strip '\n'
        # so we insert '\n###\n' between concated text instead of '\n' to avoid mismatch
        return self.textblk_break.join(text_list)

    def text2textlist(self, text: str) -> List[str]:
        breaker = self.textblk_break.replace('\n', '') or '\n'
        text_list = text.split(breaker)
        return [text.lstrip().rstrip() for text in text_list]

    def translate_textblk_lst(self, textblk_lst: List[TextBlock]):
        text_list = [blk.get_text() for blk in textblk_lst]
        translations = self.translate(text_list)
        for tr, blk in zip(translations, textblk_lst):
            for callback in self.postprocess_hooks:
                tr = callback(tr, blk=blk)
            blk.translation = tr

    def supported_languages(self) -> List[str]:
        return self.valid_lang_list

    @property
    def supported_tgt_list(self) -> List[str]:
        return self.valid_lang_list

    @property
    def supported_src_list(self) -> List[str]:
        return self.valid_lang_list
    
    def _chs2cht(self, text: str, blk: TextBlock = None):
        return chs2cht(text) if self.lang_target == '繁體中文' else text
        
    def delay(self) -> float:
        if 'delay' in self.setup_params:
            if delay := self.setup_params['delay']:
                try:
                    return float(delay)
                except:
                    pass
        return 0.


@register_translator('google')
class GoogleTranslator(TranslatorBase):

    concate_text = True
    setup_params: Dict = {
        'delay': '0.0',
        'url': {
            'type': 'selector',
            'options': [
                # 'https://translate.google.cn/m',
                'https://translate.google.com/m'
            ],
            'select': 'https://translate.google.com/m'
        },
        
    }
    
    def _setup_translator(self):
        self.lang_map['简体中文'] = 'zh-CN'
        self.lang_map['繁體中文'] = 'zh-TW'
        self.lang_map['日本語'] = 'ja'
        self.lang_map['English'] = 'en'
        self.lang_map['한국어'] = 'ko'
        self.lang_map['Tiếng Việt'] = 'vi'
        self.lang_map['čeština'] = 'cs'
        self.lang_map['Nederlands'] = 'nl'
        self.lang_map['français'] = 'fr'
        self.lang_map['Deutsch'] = 'de'
        self.lang_map['magyar nyelv'] = 'hu'
        self.lang_map['italiano'] = 'it'
        self.lang_map['polski'] = 'pl'
        self.lang_map['português'] = 'pt'
        self.lang_map['limba română'] = 'ro'
        self.lang_map['русский язык'] = 'ru'
        self.lang_map['español'] = 'es'
        self.lang_map['Türk dili'] = 'tr'

        from .google_trans import GoogleTranslator
        self.googletrans = GoogleTranslator()
        
    def _translate(self, text: Union[str, List]) -> Union[str, List]:
        self.googletrans._source = self.lang_map[self.lang_source]
        self.googletrans._url_params['sl'] = self.lang_map[self.lang_source]
        self.googletrans._target = self.lang_map[self.lang_target]
        self.googletrans._url_params['tl'] = self.lang_map[self.lang_target]
        self.googletrans.__base_url = self.setup_params['url']['select']
        return self.googletrans.translate(text)


@register_translator('papago')
class PapagoTranslator(TranslatorBase):

    concate_text = True
    setup_params: Dict = {'delay': '0.0'}
    papagoVer: str = None

    # https://github.com/zyddnys/manga-image-translator/blob/main/translators/papago.py
    def _setup_translator(self):
        self.lang_map['简体中文'] = 'zh-CN'
        self.lang_map['繁體中文'] = 'zh-TW'
        self.lang_map['日本語'] = 'ja'
        self.lang_map['English'] = 'en'
        self.lang_map['한국어'] = 'ko'
        self.lang_map['Tiếng Việt'] = 'vi'
        self.lang_map['français'] = 'fr'
        self.lang_map['Deutsch'] = 'de'
        self.lang_map['italiano'] = 'it'
        self.lang_map['português'] = 'pt'
        self.lang_map['русский язык'] = 'ru'
        self.lang_map['español'] = 'es'        

        if self.papagoVer is None:
            script = requests.get('https://papago.naver.com', proxies=PROXY)
            mainJs = re.search(r'\/(main.*\.js)', script.text)[1]
            papagoVerData = requests.get(
                f'https://papago.naver.com/{mainJs}', proxies=PROXY
            )
            papagoVer = re.search(r'"PPG .*,"(v[^"]*)', papagoVerData.text)[1]
            self.papagoVer = PapagoTranslator.papagoVer = papagoVer

    def _translate(self, text: Union[str, List]) -> Union[str, List]:
        data = {
            'source': self.lang_map[self.lang_source],
            'target': self.lang_map[self.lang_target],
            'text': text,
            'honorific': "false",
        }
        PAPAGO_URL = 'https://papago.naver.com/apis/n2mt/translate'
        guid = uuid.uuid4()
        timestamp = int(time.time() * 1000)
        key = self.papagoVer.encode("utf-8")
        code = f"{guid}\n{PAPAGO_URL}\n{timestamp}".encode("utf-8")
        token = base64.b64encode(hmac.new(key, code, "MD5").digest()).decode("utf-8")

        headers = {
            "Authorization": f"PPG {guid}:{token}",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Timestamp": str(timestamp),
        }
        resp = requests.post(PAPAGO_URL, data, headers=headers)
        return resp.json()['translatedText']
        

@register_translator('caiyun')
class CaiyunTranslator(TranslatorBase):

    concate_text = False
    cht_require_convert = True
    setup_params: Dict = {
        'token': '',
        'delay': '0.0'
    }

    def _setup_translator(self):
        self.lang_map['简体中文'] = 'zh'
        self.lang_map['繁體中文'] = 'zh'
        self.lang_map['日本語'] = 'ja'
        self.lang_map['English'] = 'en'  
        
    def _translate(self, text: Union[str, List]) -> Union[str, List]:

        url = "http://api.interpreter.caiyunai.com/v1/translator"
        token = self.setup_params['token']
        if token == '' or token is None:
            raise MissingTranslatorParams('token')

        direction = (
            f'{self.lang_map[self.lang_source]}2{self.lang_map[self.lang_target]}'
        )

        payload = {
            "source": text,
            "trans_type": direction,
            "request_id": "demo",
            "detect": True,
        }

        headers = {
            "content-type": "application/json",
            "x-authorization": f"token {token}",
        }

        response = requests.request("POST", url, data=json.dumps(payload), headers=headers)
        return json.loads(response.text)["target"]


@register_translator('baidu')
class BaiduTranslator(TranslatorBase):
    concate_text = False
    cht_require_convert = True
    setup_params: Dict = {
        'token': '',
        'appId': '',
        'delay': '0.0'
    }
    @staticmethod
    def get_json(from_lang, to_lang, query_text,BAIDU_APP_ID,BAIDU_SECRET_KEY):
        salt = random.randint(32768, 65536)
        sign = BAIDU_APP_ID + query_text + str(salt) + BAIDU_SECRET_KEY
        sign = sign.encode('utf-8')
        m1 = hashlib.md5()
        m1.update(sign)
        sign = m1.hexdigest()
        return {
            "appid": BAIDU_APP_ID,
            "q": query_text,
            "from": from_lang,
            "to": to_lang,
            "salt": str(salt),
            "sign": sign,
        }

    def _setup_translator(self):
        self.lang_map['简体中文'] = 'zh'
        self.lang_map['繁體中文'] = 'cht'
        self.lang_map['日本語'] = 'jp'
        self.lang_map['English'] = 'en'  
    
    def _translate(self, text: Union[str, List]) -> Union[str, List]:

        n_queries = []
        query_split_sizes = []
        for query in text:
            batch = query.split('\n')
            query_split_sizes.append(len(batch))
            n_queries.extend(batch)
        token = self.setup_params['token']
        appId = self.setup_params['appId']
        if token == '' or token is None:
            raise MissingTranslatorParams('token')
        if appId == '' or appId is None:
            raise MissingTranslatorParams('appId')

        payload = self.get_json(self.lang_map[self.lang_source], self.lang_map[self.lang_target], '\n'.join(n_queries),appId,token)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }

        response = requests.request("POST", 'https://fanyi-api.baidu.com/api/trans/vip/translate', data=payload, headers=headers)
        result = json.loads(response.text)
        result_list = []
        if "trans_result" not in result:
            raise MissingTranslatorParams(f'Baidu returned invalid response: {result}\nAre the API keys set correctly?')
        for ret in result["trans_result"]:
            result_list.extend(iter(ret["dst"].split('\n')))
        # Join queries that had \n back together
        translations = []
        i = 0
        for size in query_split_sizes:
            translations.append('\n'.join(result_list[i:i+size]))
            i += size

        return translations
    

@register_translator('Deepl')
class DeeplTranslator(TranslatorBase):

    concate_text = False
    cht_require_convert = True
    setup_params: Dict = {
        'api_key': '',
        'delay': '0.0',
    }

    def _setup_translator(self):
        self.lang_map['简体中文'] = 'zh'
        self.lang_map['日本語'] = 'ja'
        self.lang_map['English'] = 'EN-US'
        self.lang_map['français'] = 'fr'
        self.lang_map['Deutsch'] = 'de'
        self.lang_map['italiano'] = 'it'
        self.lang_map['português'] = 'pt'
        self.lang_map['русский язык'] = 'ru'
        self.lang_map['español'] = 'es'
        self.lang_map['български език'] = 'bg'
        self.lang_map['Český Jazyk'] = 'cs'
        self.lang_map['Dansk'] = 'da'
        self.lang_map['Ελληνικά'] = 'el'
        self.lang_map['Eesti'] = 'et'
        self.lang_map['Suomi'] = 'fi'
        self.lang_map['Magyar'] = 'hu'
        self.lang_map['Lietuvių'] = 'lt'
        self.lang_map['latviešu'] = 'lv'
        self.lang_map['Nederlands'] = 'nl'
        self.lang_map['Język polski'] = 'pl'
        self.lang_map['Română'] = 'ro'
        self.lang_map['Slovenčina'] = 'sk'
        self.lang_map['Slovenščina'] = 'sl'
        self.lang_map['Svenska'] = 'sv'
        
    def _translate(self, text: Union[str, List]) -> Union[str, List]:
        api_key = self.setup_params['api_key']
        translator = deepl.Translator(api_key)
        source = self.lang_map[self.lang_source]
        target = self.lang_map[self.lang_target]
        if source == 'EN-US':
            source = "EN"
        result = translator.translate_text(text, source_lang=source, target_lang=target)
        return [i.text for i in result]
    


SUGOIMODEL_TRANSLATOR_DIRPATH = 'data/models/sugoi_translator/'
SUGOIMODEL_TOKENIZATOR_PATH = (
    f"{SUGOIMODEL_TRANSLATOR_DIRPATH}spm.ja.nopretok.model"
)
@register_translator('Sugoi')
class SugoiTranslator(TranslatorBase):

    concate_text = False
    setup_params: Dict = {
        'device': {
            'type': 'selector',
            'options': ['cpu', 'cuda'],
            'select': 'cpu'
        }
    }

    def _setup_translator(self):
        self.lang_map['日本語'] = 'ja'
        self.lang_map['English'] = 'en'
        
        self.translator = ctranslate2.Translator(SUGOIMODEL_TRANSLATOR_DIRPATH, device=self.setup_params['device']['select'])
        self.tokenizator = spm.SentencePieceProcessor(model_file=SUGOIMODEL_TOKENIZATOR_PATH)

    def _translate(self, text: Union[str, List]) -> Union[str, List]:
        input_is_lst = True
        if isinstance(text, str):
            text = [text]
            input_is_lst = False

        text = [i.replace(".", "@").replace("．", "@") for i in text]
        tokenized_text = self.tokenizator.encode(text, out_type=str, enable_sampling=True, alpha=0.1, nbest_size=-1)
        tokenized_translated = self.translator.translate_batch(tokenized_text)
        text_translated = [''.join(text[0]["tokens"]).replace('▁', ' ').replace("@", ".") for text in tokenized_translated]

        return text_translated[0] if not input_is_lst else text_translated

    def updateParam(self, param_key: str, param_content):
        super().updateParam(param_key, param_content)
        if param_key == 'device':
            if hasattr(self, 'translator'):
                delattr(self, 'translator')
            self.translator = ctranslate2.Translator(SUGOIMODEL_TRANSLATOR_DIRPATH, device=self.setup_params['device']['select'])

    @property
    def supported_tgt_list(self) -> List[str]:
        return ['English']

    @property
    def supported_src_list(self) -> List[str]:
        return ['日本語']


@register_translator('Yandex')
class YandexTranslator(TranslatorBase):

    concate_text = False
    setup_params: Dict = {
        'api_key': '',
        'delay': '0.0',
    }

    def _setup_translator(self):
        self.lang_map['简体中文'] = 'zh'
        self.lang_map['日本語'] = 'ja'
        self.lang_map['English'] = 'en'
        self.lang_map['한국어'] = 'ko'
        self.lang_map['Tiếng Việt'] = 'vi'
        self.lang_map['čeština'] = 'cs'
        self.lang_map['Nederlands'] = 'nl'
        self.lang_map['français'] = 'fr'
        self.lang_map['Deutsch'] = 'de'
        self.lang_map['magyar nyelv'] = 'hu'
        self.lang_map['italiano'] = 'it'
        self.lang_map['polski'] = 'pl'
        self.lang_map['português'] = 'pt'
        self.lang_map['limba română'] = 'ro'
        self.lang_map['русский язык'] = 'ru'
        self.lang_map['español'] = 'es'
        self.lang_map['Türk dili'] = 'tr'

        self.api_url = 'https://translate.api.cloud.yandex.net/translate/v2/translate'

    def _translate(self, text: Union[str, List]) -> Union[str, List]:

        body = {
            "targetLanguageCode": self.lang_map[self.lang_target],
            "texts": text,
            "folderId": '',
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": "Api-Key {0}".format(self.setup_params['api_key'])
        }

        translations = requests.post(self.api_url, json=body, headers=headers).json()['translations']
        if isinstance(text, str):
            return translations[0]['text']
        tr_list = []
        for tr in translations:
            if 'text' in tr:
                tr_list.append(tr['text'])
            else:
                tr_list.append('')
        return tr_list

# "dummy translator" is the name showed in the app
# @register_translator('dummy translator')
# class DummyTranslator(TranslatorBase):

#     concate_text = True

#     # parameters showed in the config panel. 
#     # keys are parameter names, if value type is str, it will be a text editor(required key)
#     # if value type is dict, you need to spicify the 'type' of the parameter, 
#     # following 'device' is a selector, options a cpu and cuda, default is cpu
#     setup_params: Dict = {
#         'api_key': '', 
#         'device': {
#             'type': 'selector',
#             'options': ['cpu', 'cuda'],
#             'select': 'cpu'
#         }
#     }

#     def _setup_translator(self):
#         '''
#         do the setup here.  
#         keys of lang_map are those languages options showed in the app, 
#         assign corresponding language keys accepted by API to supported languages.  
#         Only the languages supported by the translator are assigned here, this translator only supports Japanese, and English.
#         For a full list of languages see LANGMAP_GLOBAL in translator.__init__
#         '''
#         self.lang_map['日本語'] = 'ja'
#         self.lang_map['English'] = 'en'  
        
#     def _translate(self, text: Union[str, List]) -> Union[str, List]:
#         '''
#         do the translation here.  
#         This translator do nothing but return the original text.
#         '''
#         source = self.lang_map[self.lang_source]
#         target = self.lang_map[self.lang_target]
        
#         translation = text
#         return translation

#     def updateParam(self, param_key: str, param_content):
#         '''
#         required only if some state need to be updated immediately after user change the translator params,
#         for example, if this translator is a pytorch model, you can convert it to cpu/gpu here.
#         '''
#         super().updateParam(param_key, param_content)
#         if param_key == 'device':
#             # get current state from setup_params
#             # self.model.to(self.setup_params['device']['select'])
#             pass

#     @property
#     def supported_tgt_list(self) -> List[str]:
#         '''
#         required only if the translator's language supporting is asymmetric, 
#         for example, this translator only supports English -> Japanese, no Japanese -> English.
#         '''
#         return ['English']

#     @property
#     def supported_src_list(self) -> List[str]:
#         '''
#         required only if the translator's language supporting is asymmetric.
#         '''
#         return ['日本語']