from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from . models import ShippingAddress, Order, OrderItem
from cart.cart import Cart
from django.http import JsonResponse
from django.core.mail import send_mail
from django.conf import settings
from store.models import Product
from decimal import Decimal
from account.models import award_points_for_order, RewardAccount
from django.contrib import messages

'''
def checkout(request):
    # Users with accounts -- Pre-fill the form
    if request.user.is_authenticated:
        try:
            # Authenticated users WITH shipping information 
            shipping_address = ShippingAddress.objects.get(user=request.user.id)
            reward_account = RewardAccount.objects.get(user=request.user)
            context = {'shipping': shipping_address, 'reward_account': reward_account}
            return render(request, 'payment/checkout.html', context=context)
        except:
            # Authenticated users with NO shipping information
            reward_account = RewardAccount.objects.create(
                user=request.user,
                total_points=0,
                lifetime_points=0
            )
            return render(request, 'payment/checkout.html', context=context)
    else:
        # Guest users
        return render(request, 'payment/checkout.html')
'''

def checkout(request):
    """
    Checkout view with rewards integration - FIXED VERSION
    """
    cart = Cart(request)
    cart_total = cart.get_total()
    
    context = {
        'cart': cart,
        'cart_total': cart_total,
    }
    
    # Add reward account for authenticated users
    if request.user.is_authenticated:
        try:
            # Try to get existing reward account
            reward_account = RewardAccount.objects.get(user=request.user)
        except RewardAccount.DoesNotExist:
            # Create new reward account if doesn't exist
            reward_account = RewardAccount.objects.create(
                user=request.user,
                total_points=Decimal('0.00'),
                lifetime_points=Decimal('0.00')
            )
        
        context['reward_account'] = reward_account
    
    return render(request, 'payment/checkout.html', context)

def complete_order(request):
    if request.POST.get('action') == 'post':
        name = request.POST.get('name')
        email = request.POST.get('email')
        address1 = request.POST.get('address1')
        address2 = request.POST.get('address2')
        city = request.POST.get('city')
        state = request.POST.get('state')
        zipcode = request.POST.get('zipcode')
        
        # ══════════════════════════════════════════════════════════════
        # NEW: Get rewards redemption amount
        # ══════════════════════════════════════════════════════════════
        rewards_to_apply = Decimal(request.POST.get('rewards_applied', '0'))

        # All-in-one shipping address
        shipping_address = (address1 + "\n" + address2 + "\n" +
        city + "\n" + state + "\n" + zipcode)

        # Shopping cart information 
        cart = Cart(request)

        # Get the original total price of items
        original_total = cart.get_total()
        
        # ══════════════════════════════════════════════════════════════
        # NEW: Calculate final total after rewards redemption
        # ══════════════════════════════════════════════════════════════
        rewards_redeemed = Decimal('0.00')
        
        if request.user.is_authenticated and rewards_to_apply > 0:
            try:
                # Get user's reward account
                reward_account = RewardAccount.objects.get(user=request.user)
                
                # Validate redemption amount
                if rewards_to_apply > reward_account.total_points:
                    # User trying to redeem more than they have
                    response = JsonResponse({
                        'success': False,
                        'error': f'You only have ${reward_account.total_points} in rewards available.'
                    })
                    return response
                
                if rewards_to_apply > original_total:
                    # User trying to redeem more than order total
                    response = JsonResponse({
                        'success': False,
                        'error': f'Rewards cannot exceed order total of ${original_total}.'
                    })
                    return response
                
                # Valid redemption amount
                rewards_redeemed = rewards_to_apply
                
            except RewardAccount.DoesNotExist:
                # User has no reward account yet
                rewards_redeemed = Decimal('0.00')
        
        # Calculate final total after applying rewards
        total_cost = original_total - rewards_redeemed
        
        # Ensure total doesn't go negative
        if total_cost < 0:
            total_cost = Decimal('0.00')
        # ══════════════════════════════════════════════════════════════

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
                amount_paid=total_cost,  # Final amount after rewards
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

            # ══════════════════════════════════════════════════════════════
            # REWARDS PROCESSING
            # ══════════════════════════════════════════════════════════════
            try:
                # STEP 1: Redeem rewards if any were applied
                if rewards_redeemed > 0:
                    reward_account = RewardAccount.objects.get(user=request.user)
                    
                    # Deduct rewards from account
                    reward_account.total_points -= rewards_redeemed
                    reward_account.save()
                    
                    # Create redemption transaction (negative)
                    RewardTransaction.objects.create(
                        user=request.user,
                        order=order,
                        order_total=original_total,
                        points_earned=-rewards_redeemed,  # Negative for redemption
                        transaction_type='REDEEMED',
                        description=f'Rewards redeemed on order #{order.id}'
                    )
                    
                    print(f"✓ Rewards redeemed: ${rewards_redeemed} from {request.user.username}")
                
                # STEP 2: Award new rewards based on FINAL total (after redemption)
                if total_cost > 0:
                    reward_transaction = award_points_for_order(
                        user=request.user,
                        order=order,
                        order_total=total_cost  # Calculate rewards on reduced amount
                    )
                    
                    print(f"✓ New rewards awarded: ${reward_transaction.points_earned} to {request.user.username}")
                    rewards_earned = float(reward_transaction.points_earned)
                else:
                    # Order was fully paid with rewards
                    rewards_earned = 0
                
            except Exception as e:
                print(f"✗ Error processing rewards: {e}")
                rewards_earned = 0
            # ══════════════════════════════════════════════════════════════

        else:
            # Guest users - no rewards
            order = Order.objects.create(
                full_name=name, 
                email=email, 
                shipping_address=shipping_address,
                amount_paid=original_total  # Guests pay full price
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
            rewards_redeemed = 0

        # Send confirmation email
        try:
            # Enhanced email with rewards info
            email_body = (
                'Hi! ' + '\n\n' + 
                'Thank you for placing your order' + '\n\n' +
                'Please see your order below: ' + '\n\n' + 
                str(product_list) + '\n\n'
            )
            
            # Add order totals
            if rewards_redeemed > 0:
                email_body += (
                    f'Original Total: ${original_total}\n' +
                    f'Rewards Applied: -${rewards_redeemed}\n' +
                    f'Final Total Paid: ${total_cost}\n\n'
                )
            else:
                email_body += f'Total paid: ${total_cost}\n\n'
            
            # Add new rewards info
            if request.user.is_authenticated and rewards_earned > 0:
                email_body += (
                    '\n' + 
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
            print(f"Email sending failed: {e}")

        order_success = True
        
        # Enhanced response with rewards info
        response_data = {
            'success': order_success,
            'order_id': order_id,
            'original_total': float(original_total),
            'final_total': float(total_cost)
        }
        
        # Add redemption info
        if rewards_redeemed > 0:
            response_data['rewards_redeemed'] = float(rewards_redeemed)
            response_data['savings_message'] = f'You saved ${rewards_redeemed:.2f} with rewards!'
        
        # Add new rewards earned info
        if request.user.is_authenticated and rewards_earned > 0:
            response_data['rewards_earned'] = rewards_earned
            response_data['rewards_message'] = f'You earned ${rewards_earned:.2f} in new rewards!'
        
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

def paypal_client_id(request):
    """
    Context processor to make PayPal client-id available in all templates
    """
    return {
        'paypal_client_id': settings.PAYPAL_CLIENT_ID
    }

def payment_failed(request):
    return render(request, 'payment/payment-failed.html')