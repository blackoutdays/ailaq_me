from django_filters import rest_framework as filters
from ailaq.models import PsychologistProfile
from django.db.models import Q

class PsychologistProfileFilter(filters.FilterSet):
    full_name = filters.CharFilter(field_name="get_full_name", lookup_expr="icontains", label="Поиск по имени")
    gender = filters.CharFilter(field_name="application__gender", lookup_expr="iexact")
    min_price = filters.NumberFilter(method="filter_min_price")
    max_price = filters.NumberFilter(method="filter_max_price")
    city = filters.CharFilter(field_name="application__city", lookup_expr="icontains")
    is_verified = filters.BooleanFilter(field_name="is_verified")
    communication_language = filters.CharFilter(method="filter_communication_language")
    specialization = filters.CharFilter(field_name="application__qualification", lookup_expr="icontains")
    session_format = filters.ChoiceFilter(choices=[('ONLINE', 'Онлайн'), ('OFFLINE', 'Оффлайн')], label='Формат сессии')

    class Meta:
        model = PsychologistProfile
        fields = [
            "gender",
            "city",
            "is_verified",
            "communication_language",
            "specialization",
            "session_format",
        ]

    def filter_min_price(self, queryset, name, value):
        return queryset.filter(application__service_sessions__contains=[{"price": value}])

    def filter_max_price(self, queryset, name, value):
        return queryset.filter(application__service_sessions__contains=[{"price": value}])

    def filter_communication_language(self, queryset, name, value):
        languages = [lang.strip() for lang in value.split(',') if lang.strip()]
        q = Q()
        for lang in languages:
            q |= Q(application__communication_language__contains=[lang])
        return queryset.filter(q)