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

class PreferredPsychologistGenderEnum(Enum):
    MALE = 'Мужской'
    FEMALE = 'Женский'

class CommunicationLanguageEnum(Enum):
    RU = 'Русский'
    EN = 'Английский'
    KK = 'Казахский'