from enum import Enum

class ClientGenderEnum(Enum):
    MALE = 'Мужской'
    FEMALE = 'Женский'

class PsychologistGenderEnum(Enum):
    MALE = 'Мужской'
    FEMALE = 'Женский'
    OTHER = 'Другой'

class LanguageEnum(Enum):
    RU = 'Русский'
    EN = 'Английский'
    KZ = 'Казахский'

class PsychologistAgeEnum(Enum):
    AGE_18_25 = 'От 18 до 25'
    AGE_25_35 = 'От 25 до 35'
    AGE_35_PLUS = 'От 35'

class PreferredPsychologistGenderEnum(Enum):
    MALE = 'Мужской'
    FEMALE = 'Женский'

class CommunicationLanguageEnum(Enum):
    RU = 'Русский'
    EN = 'Английский'
    KZ = 'Казахский'