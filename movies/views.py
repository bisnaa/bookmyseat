from django.shortcuts import render, redirect, get_object_or_404
from .models import (Movie,Theater,Seat,Booking,SeatReservation,Payment,Genre,Language)
import uuid
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from urllib.parse import urlparse, parse_qs
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.contrib.admin.views.decorators import staff_member_required
from django.core.cache import cache
from django.db.models import Count, Sum
from datetime import timedelta
from django.db.models.functions import ExtractHour
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
import threading
import logging


logger = logging.getLogger(__name__)
def extract_youtube_video_id(url):
    try:
        parsed_url = urlparse(url)

        if parsed_url.hostname in ['www.youtube.com', 'youtube.com']:
            return parse_qs(parsed_url.query).get('v', [None])[0]

        if parsed_url.hostname == 'youtu.be':
            return parsed_url.path[1:]

        return None

    except:
        return None


from django.core.paginator import Paginator

def movie_list(request):

    movies = Movie.objects.all().prefetch_related(
        'genre'
    ).select_related(
        'language'
    )

    selected_genres = request.GET.getlist(
        'genre'
    )

    selected_languages = request.GET.getlist(
        'language'
    )

    search_query = request.GET.get('search')

    sort_by = request.GET.get('sort')

    if search_query:

        movies = movies.filter(
            name__icontains=search_query
        )

    if selected_genres:

        movies = movies.filter(
            genre__id__in=selected_genres
        ).distinct()

    if selected_languages:

        movies = movies.filter(
            language__id__in=selected_languages
        )

    if sort_by == 'rating':

        movies = movies.order_by('-rating')

    elif sort_by == 'name':

        movies = movies.order_by('name')

    paginator = Paginator(movies, 6)

    page_number = request.GET.get('page')

    page_obj = paginator.get_page(page_number)

    genres = Genre.objects.annotate(
        movie_count=Count('movies')
    )

    languages = Language.objects.annotate(
        movie_count=Count('movies')
    )

    return render(

        request,

        'movies/movie_list.html',

        {
            'page_obj': page_obj,

            'genres': genres,

            'languages': languages,

            'selected_genres':
            selected_genres,

            'selected_languages':
            selected_languages,

            'sort_by': sort_by
        }
    )
def theater_list(request, movie_id):

    movie = get_object_or_404(Movie, id=movie_id)

    theater = Theater.objects.filter(movie=movie)

    return render(
        request,
        'movies/theater_list.html',
        {
            'movie': movie,
            'theaters': theater
        }
    )


def movie_detail(request, movie_id):

    movie = get_object_or_404(Movie, id=movie_id)

    video_id = None

    if movie.trailer_url:
        video_id = extract_youtube_video_id(
            movie.trailer_url
        )

    return render(
        request,
        'movies/movie_detail.html',
        {
            'movie': movie,
            'video_id': video_id
        }
    )


def clear_expired_reservations():

    expired_reservations = SeatReservation.objects.filter(
        expires_at__lt=timezone.now()
    )

    expired_reservations.delete()

def send_booking_email_async(
    user,
    movie,
    theater,
    seat,
    payment_id

):

    def send_email():

        retry_count = 3

        while retry_count > 0:

            try:

                subject = (
                    'Movie Ticket Booking Confirmation'
                )

                html_content = render_to_string(

                    'emails/booking_confirmation.html',

                    {
                        'user': user,
                        'movie': movie,
                        'theater': theater,
                        'seat': seat,
                        'payment_id': payment_id
                    }
                )

                email = EmailMultiAlternatives(

                    subject,

                    '',

                    'noreply@bookmyseat.com',

                    [user.email]
                )

                email.attach_alternative(
                    html_content,
                    "text/html"
                )

                email.send()

                logger.info(
                    f"Booking email sent to "
                    f"{user.email}"
                )

                break

            except Exception as e:

                retry_count -= 1

                logger.error(
                    f"Email sending failed: {e}"
                )

    threading.Thread(
        target=send_email
    ).start()

@login_required(login_url='/login/')
def book_seats(request, theater_id):

    theaters = get_object_or_404(
        Theater,
        id=theater_id
    )

    seats = Seat.objects.filter(
        theater=theaters
    )

    clear_expired_reservations()

    if request.method == 'POST':

        selected_Seats = request.POST.getlist('seats')

        error_seats = []

        if not selected_Seats:

            return render(
                request,
                "movies/seat_selection.html",
                {
                    'theaters': theaters,
                    "seats": seats,
                    'error': "No seat selected"
                }
            )

        for seat_id in selected_Seats:

            try:

                with transaction.atomic():

                    seat = Seat.objects.select_for_update().get(
                        id=seat_id,
                        theater=theaters
                    )

                    if seat.is_booked:
                        error_seats.append(
                            seat.seat_number
                        )
                        continue

                    existing_reservation = (
                        SeatReservation.objects.filter(
                            seat=seat,
                            expires_at__gt=timezone.now()
                        ).first()
                    )

                    if existing_reservation:
                        error_seats.append(
                            seat.seat_number
                        )
                        continue

                booking = Booking.objects.create(
                    user=request.user,
                    seat=seat,
                    movie=theaters.movie,
                    theater=theaters
                )

                seat.is_booked = True
                seat.save()

                send_booking_email_async(
                    request.user,
                    booking.movie,
                    booking.theater,
                    booking.seat,
                    "BOOKING_PAYMENT"
                )

            except IntegrityError:

                error_seats.append(
                    seat.seat_number
                )

        if error_seats:

            error_message = (
                f"The following seats are already "
                f"reserved/booked: "
                f"{', '.join(error_seats)}"
            )

            return render(
                request,
                'movies/seat_selection.html',
                {
                    'theaters': theaters,
                    "seats": seats,
                    'error': error_message
                }
            )

        return redirect('profile')

    active_reservations = SeatReservation.objects.filter(
        seat__theater=theaters,
        expires_at__gt=timezone.now()
    )

    active_reservation_ids = (
        active_reservations.values_list(
            'seat_id',
            flat=True
        )
    )

    return render(
        request,
        'movies/seat_selection.html',
        {
            'theaters': theaters,
            "seats": seats,
            'active_reservations': active_reservations,
            'active_reservation_ids': active_reservation_ids
        }
    )

@login_required(login_url='/login/')
def create_payment(request):

    if request.method == 'POST':

        amount = request.POST.get('amount')

        fake_order_id = f"order_{uuid.uuid4().hex[:12]}"

        payment = Payment.objects.create(
            user=request.user,
            razorpay_order_id=fake_order_id,
            amount=amount,
            status='PENDING'
        )

        return JsonResponse({
            'success': True,
            'order_id': fake_order_id,
            'payment_id': payment.id,
            'status': payment.status
        })

    return JsonResponse({
        'success': False,
        'message': 'Invalid request'
    })

@login_required(login_url='/login/')
def verify_payment(request):

    if request.method == 'POST':

        payment_id = request.POST.get('payment_id')

        try:

            payment = Payment.objects.get(
                id=payment_id
            )

            if payment.status == 'SUCCESS':

                return JsonResponse({
                    'success': False,
                    'message': 'Duplicate payment attempt detected'
                })

            fake_signature = request.POST.get(
                'signature'
            )

            if fake_signature != "VALID_SIGNATURE":

                payment.status = 'FAILED'
                payment.save()

                return JsonResponse({
                    'success': False,
                    'message': 'Payment verification failed'
                })

            payment.status = 'SUCCESS'

            payment.razorpay_payment_id = (
                f"pay_{uuid.uuid4().hex[:10]}"
            )

            payment.razorpay_signature = fake_signature

            payment.save()
          
#             booking = Booking.objects.create(
#                 user=request.user,
#                 seat=Seat.objects.filter(
#                     is_booked=False
#                 ).first(),
#                 movie=Theater.objects.first().movie,
#                 theater=Theater.objects.first()
#             )

            

#             payment.booking = booking
#             payment.save()
#             send_booking_email_async(
#     request.user,
#     booking.movie,
#     booking.theater,
#     booking.seat,
#     payment.razorpay_payment_id
# )

            return JsonResponse({
                'success': True,
                'message': 'Payment verified successfully'
            })

        except Payment.DoesNotExist:

            return JsonResponse({
                'success': False,
                'message': 'Payment not found'
            })

    return JsonResponse({
        'success': False,
        'message': 'Invalid request'
    })

@csrf_exempt
def payment_webhook(request):

    if request.method == 'POST':

        payment_id = request.POST.get(
            'payment_id'
        )

        webhook_signature = request.POST.get(
            'webhook_signature'
        )

        try:

            payment = Payment.objects.get(
                id=payment_id
            )

            if payment.status == 'SUCCESS':

                return JsonResponse({
                    'success': False,
                    'message':
                    'Duplicate webhook ignored'
                })

            if webhook_signature != "WEBHOOK_SECRET":

                return JsonResponse({
                    'success': False,
                    'message':
                    'Invalid webhook signature'
                })

            payment.status = 'SUCCESS'

            payment.save()

            return JsonResponse({
                'success': True,
                'message':
                'Webhook processed successfully'
            })

        except Payment.DoesNotExist:

            return JsonResponse({
                'success': False,
                'message':
                'Payment not found'
            })

    return JsonResponse({
        'success': False,
        'message': 'Invalid request'
    })


@staff_member_required
def admin_dashboard(request):

    dashboard_data = cache.get('dashboard_data')

    if not dashboard_data:

        today = timezone.now()

        total_revenue = Payment.objects.filter(
            status='SUCCESS'
        ).aggregate(
            total=Sum('amount')
        )

        daily_revenue = Payment.objects.filter(
            status='SUCCESS',
            created_at__date=today.date()
        ).aggregate(
            total=Sum('amount')
        )

        weekly_revenue = Payment.objects.filter(
            status='SUCCESS',
            created_at__gte=today - timedelta(days=7)
        ).aggregate(
            total=Sum('amount')
        )

        monthly_revenue = Payment.objects.filter(
            status='SUCCESS',
            created_at__gte=today - timedelta(days=30)
        ).aggregate(
            total=Sum('amount')
        )

        popular_movies = Movie.objects.annotate(
            total_bookings=Count('booking')
        ).order_by('-total_bookings')[:5]
    busiest_theaters = Theater.objects.annotate(

        total_seats=Count('seats'),

        booked_seats=Count('seats__booking')

    ).order_by('-booked_seats')[:5]

    for theater in busiest_theaters:

        if theater.total_seats > 0:

            theater.occupancy_rate = (
                theater.booked_seats /
                theater.total_seats
            ) * 100

        else:

            theater.occupancy_rate = 0
        

        peak_hours = Booking.objects.annotate(
            hour=ExtractHour('booked_at')
        ).values('hour').annotate(
            total=Count('id')
        ).order_by('-total')[:5]
        total_payments = Payment.objects.count()

    cancelled_payments = Payment.objects.filter(
        status='CANCELLED'
    ).count()

    cancellation_rate = 0

    if total_payments > 0:

        cancellation_rate = (
        cancelled_payments / total_payments
    ) * 100

        dashboard_data = {

            'total_revenue': total_revenue,

            'daily_revenue': daily_revenue,

            'weekly_revenue': weekly_revenue,

            'monthly_revenue': monthly_revenue,

            'popular_movies': popular_movies,

            'busiest_theaters': busiest_theaters,

            'peak_hours': peak_hours,
            'cancellation_rate': cancellation_rate,
        }

        cache.set(
            'dashboard_data',
            dashboard_data,
            timeout=300
        )

    return render(
        request,
        'movies/admin_dashboard.html',
        dashboard_data
    )
