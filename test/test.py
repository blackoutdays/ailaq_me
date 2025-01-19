from django.test import TestCase
from ailaq.models import PsychologistProfile, Session, Review, CustomUser, ClientProfile

class PsychologistProfileTests(TestCase):
    def setUp(self):
        CustomUser.objects.all().delete()
        PsychologistProfile.objects.all().delete()
        ClientProfile.objects.all().delete()

        # Создаем пользователя психолога
        self.user = CustomUser.objects.create_user(
            email="test@example.com",
            password="password123",
            is_psychologist=True
        )
        self.psychologist_profile = PsychologistProfile.objects.get_or_create(user=self.user)[0]

        # Создаем клиента
        self.client_user = CustomUser.objects.create_user(
            email="client@example.com",
            password="password123",
            is_psychologist=False
        )
        self.client_profile = ClientProfile.objects.get_or_create(email=self.client_user)[0]

        # Создаём завершённые сессии и отзывы
        for i in range(5):  # 5 завершённых сессий с отзывами
            session = Session.objects.create(
                psychologist=self.psychologist_profile,
                client=self.client_profile,
                status="COMPLETED",
                start_time="2023-01-01T10:00:00Z",
                end_time="2023-01-01T11:00:00Z",
            )
            Review.objects.create(
                session=session,
                rating=4 + i % 2,  # Рейтинги 4 и 5
                text=f"Отзыв {i + 1}"
            )

        # Создаём не завершённую сессию
        Session.objects.create(
            psychologist=self.psychologist_profile,
            client=self.client_profile,
            status="SCHEDULED",
            start_time="2023-01-02T10:00:00Z"
        )

    def test_review_count(self):
        # Получаем все завершённые отзывы
        sessions_qs = self.psychologist_profile.sessions.filter(status="COMPLETED")
        review_count = Review.objects.filter(session__in=sessions_qs).count()

        # Проверяем, что количество равно ожидаемому (5)
        self.assertEqual(review_count, 5)

    def test_average_rating(self):
        # Проверяем средний рейтинг
        average_rating = self.psychologist_profile.get_average_rating()
        print(f"Calculated average rating: {average_rating}")

        # Отладка отзывов
        sessions_qs = self.psychologist_profile.sessions.filter(status="COMPLETED")
        reviews = Review.objects.filter(session__in=sessions_qs)
        for review in reviews:
            print(f"Review ID: {review.id}, Rating: {review.rating}")

        self.assertEqual(round(average_rating, 1), 4.5)