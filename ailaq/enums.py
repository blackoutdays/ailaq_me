from enum import Enum

class ClientGenderEnum(Enum):
    MALE = 'Мужской'
    FEMALE = 'Женский'

class PsychologistGenderEnum(Enum):
    MALE = 'Мужской'
    FEMALE = 'Женский'
    OTHER = 'Другой'

class PreferredPsychologistGenderEnum(Enum):
    MALE = 'Мужской'
    FEMALE = 'Женский'

class CommunicationLanguageEnum(Enum):
    RU = 'Русский'
    EN = 'Английский'
    KK = 'Казахский'
    KZ = 'Казахский'

def get_language_code(language_code):
    if language_code == 'KK' or language_code == 'KZ':
        return 'Казахский'
    else:
        return CommunicationLanguageEnum[language_code].value

class ProblemEnum(Enum):
    aggression = 'Агрессия, ссоры и конфликты'
    PREGNANCY = 'Беременность и материнство'
    BAD_HABITS = 'Вредные привычки и зависимости'
    DEPRESSION = 'Депрессия и стресс'
    LIFE_CRISIS = 'Жизненные кризисы'
    CHOICE = 'Затрудняюсь с выбором'
    ISOLATION = 'Изоляция и социальная тревога'
    CAREER = 'Карьера, финансы и планы на жизнь'
    IDENTITY_CRISIS = 'Кризисы идентичности и самовосприятия'
    DEVELOPMENT = 'Мое развитие и самоопределение'
    SLEEP_DISORDER = 'Нарушение сна и бессонница'
    UNKNOWN_EMOTIONS = 'Непонятные эмоции'
    LOW_SELF_ESTEEM = 'Неуверенность в себе'
    PANIC_ATTACKS = 'Панические атаки'
    RELATIONSHIP_BOUNDARIES = 'Проблемы с границами в отношениях'
    PROCRASTINATION = 'Прокрастинация и выгорание'
    PSYCHOSOMATICS = 'Психосоматика и физическое здоровье'
    EATING_DISORDER = 'Расстройство пищевого поведения'
    SEXUAL_RELATIONSHIPS = 'Сексуальные отношения'
    COMMUNICATION = 'Сложности в общении с людьми'
    RELATIONSHIPS = 'Сложности в отношениях'
    SELF_RELATIONSHIPS = 'Сложности в отношениях с собой'
    FAMILY = 'Сложности в семье'
    ADAPTATION = 'Сложности при адаптации к новым жизненным условиям'
    CHILDREN = 'Сложности с детьми'
    SELF_ESTEEM = 'Сложности с самооценкой'
    FEAR_OF_CHANGE = 'Страх перед переменами или новым опытом'
    ANXIETY = 'Тревога и страхи'
    LOSS = 'Утрата близкого человека'
    GUILT = 'Чувство вины или стыда'
    LONELINESS = 'Чувство одиночества'
    OTHER = 'Другая проблема'