from django.shortcuts import render
from . models import ShippingAddress, Order, OrderItem
from cart.cart import Cart
from django.http import JsonResponse
from django.core.mail import send_mail
from django.conf import settings
from store.models import Product
from decimal import Decimal
from account.models import award_points_for_order
from django.contrib import messages


def checkout(request):
    # Users with accounts -- Pre-fill the form
    if request.user.is_authenticated:
        try:
            # Authenticated users WITH shipping information 
            shipping_address = ShippingAddress.objects.get(user=request.user.id)
            context = {'shipping': shipping_address}
            return render(request, 'payment/checkout.html', context=context)
        except:
            # Authenticated users with NO shipping information
            return render(request, 'payment/checkout.html')
    else:
        # Guest users
        return render(request, 'payment/checkout.html')


def complete_order(request):
    if request.POST.get('action') == 'post':
        name = request.POST.get('name')
        email = request.POST.get('email')
        address1 = request.POST.get('address1')
        address2 = request.POST.get('address2')
        city = request.POST.get('city')
        state = request.POST.get('state')
        zipcode = request.POST.get('zipcode')

        # All-in-one shipping address
        shipping_address = (address1 + "\n" + address2 + "\n" +
        city + "\n" + state + "\n" + zipcode)

        # Shopping cart information 
        cart = Cart(request)

        # Get the total price of items
        total_cost = cart.get_total()

        # Initialize product list and validation
        product_list = []
        insufficient_stock = []

        # STEP 1: Validate stock availability for all items BEFORE processing
        for item in cart:
            product = item['product']
            quantity = item['qty']
            
            if not product.can_fulfill_order(quantity):
                insufficient_stock.append({
                    'product': product.title,
                    'requested': quantity,
                    'available': product.quantity_available
                })
        
        # If any product has insufficient stock, return error
        if insufficient_stock:
            error_message = "Unable to complete order. Insufficient stock for: "
            error_details = ", ".join([
                f"{item['product']} (requested: {item['requested']}, available: {item['available']})"
                for item in insufficient_stock
            ])
            
            response = JsonResponse({
                'success': False,
                'error': error_message + error_details
            })
            return response

        # STEP 2: Create order (stock is available for all items)
        if request.user.is_authenticated:
            order = Order.objects.create(
                full_name=name, 
                email=email, 
                shipping_address=shipping_address,
                amount_paid=total_cost, 
                user=request.user
            )
            order_id = order.pk

            # Create order items and update product inventory
            for item in cart:
                product = item['product']
                quantity = item['qty']
                price = item['price']
                
                # Create order item
                OrderItem.objects.create(
                    order_id=order_id, 
                    product=product, 
                    quantity=quantity,
                    price=price, 
                    user=request.user
                )
                
                # Update product inventory and sales tracking
                total_item_price = Decimal(str(price)) * quantity
                product.process_sale(quantity, total_item_price)
                product_list.append(product.title)

            # ═══════════════════════════════════════════════════════════════
            # REWARDS INTEGRATION - Award points for authenticated users
            # ═══════════════════════════════════════════════════════════════
            try:
                # Award rewards points based on order total
                reward_transaction = award_points_for_order(
                    user=request.user,
                    order=order,
                    order_total=total_cost
                )
                
                # Log successful reward award
                print(f"✓ Rewards awarded: ${reward_transaction.points_earned} to {request.user.username}")
                
                # Store reward info to include in response (optional)
                rewards_earned = float(reward_transaction.points_earned)
                
            except Exception as e:
                # Log error but don't fail the order
                print(f"✗ Error awarding rewards: {e}")
                rewards_earned = 0
            # ═══════════════════════════════════════════════════════════════

        else:
            # Guest users - no rewards
            order = Order.objects.create(
                full_name=name, 
                email=email, 
                shipping_address=shipping_address,
                amount_paid=total_cost
            )
            order_id = order.pk

            # Create order items and update product inventory
            for item in cart:
                product = item['product']
                quantity = item['qty']
                price = item['price']
                
                # Create order item
                OrderItem.objects.create(
                    order_id=order_id, 
                    product=product, 
                    quantity=quantity,
                    price=price
                )
                
                # Update product inventory and sales tracking
                total_item_price = Decimal(str(price)) * quantity
                product.process_sale(quantity, total_item_price)
                product_list.append(product.title)
            
            # No rewards for guest users
            rewards_earned = 0

        # Send confirmation email
        try:
            # Enhanced email with rewards info for authenticated users
            email_body = (
                'Hi! ' + '\n\n' + 
                'Thank you for placing your order' + '\n\n' +
                'Please see your order below: ' + '\n\n' + 
                str(product_list) + '\n\n' + 
                'Total paid: $' + str(total_cost)
            )
            
            # Add rewards info to email if user is authenticated
            if request.user.is_authenticated and rewards_earned > 0:
                email_body += (
                    '\n\n' + 
                    '🎁 REWARDS EARNED: $' + f"{rewards_earned:.2f}" + '\n' +
                    'Check your dashboard to see your rewards balance!'
                )
            
            send_mail(
                'Order received', 
                email_body,
                settings.EMAIL_HOST_USER, 
                [email], 
                fail_silently=False
            )
        except Exception as e:
            # Log email error but don't fail the order
            print(f"Email sending failed: {e}")

        order_success = True
        
        # Enhanced response with rewards info
        response_data = {
            'success': order_success,
            'order_id': order_id
        }
        
        # Add rewards info for authenticated users
        if request.user.is_authenticated and rewards_earned > 0:
            response_data['rewards_earned'] = rewards_earned
            response_data['rewards_message'] = f'You earned ${rewards_earned:.2f} in rewards!'
        
        response = JsonResponse(response_data)
        return response

def payment_success(request):
    # Clear shopping cart
    for key in list(request.session.keys()):
        if key == 'session_key':
            del request.session[key]
    try:
        if request.user.is_authenticated:
            # Call the reward function
            reward_transaction = award_points_for_order(
                user=request.user,
                order=order,
                order_total=order_total
            )
            
            # Add a success message
            messages.success(
                request, 
                f'Congratulations! You earned ${reward_transaction.points_earned} in rewards points!'
            )
    except Exception as e:
        # Log the error but don't fail the payment
        print(f"Error awarding rewards: {e}")

    return render(request, 'payment/payment-success.html')


def payment_failed(request):
    return render(request, 'payment/payment-failed.html')