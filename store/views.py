from django.shortcuts import render
from . models import Category, Product, Topic
from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.template.loader import render_to_string
from django.http import HttpResponse


def store(request):
    all_products = Product.objects.all()
    context = {'my_products':all_products}
    return render(request, 'store/store.html', context)

def categories(request):
    all_categories = Category.objects.all()
    return {'all_categories': all_categories}

def brands(request):
    """Context processor to get all unique brands with their product counts"""
    all_brands = Product.objects.values_list('brand', flat=True).distinct().order_by('brand')
    # Filter out empty brands and 'un-branded'
    all_brands = [brand for brand in all_brands if brand and brand.lower() != 'un-branded']
    all_topics = Topic.objects.all().order_by('name')
    return {'all_brands': all_brands, 'all_topics': all_topics,}

def list_topics(request, topic_slug=None):
    topic = get_object_or_404(Topic, slug=topic_slug)
    categories = Category.objects.filter(topic=topic)
    products = Product.objects.filter(category__in=categories)
    context = {
        'topic': topic,
        'products': products,
        'product_count': products.count(),
    }
    return render(request, 'store/list-topic.html', context)

def list_category(request, category_slug=None):
    category = get_object_or_404(Category, slug=category_slug)
    products = Product.objects.filter(category=category)
    return render(request, 'store/list-category.html', {'category':category, 'products':products})

def list_brand(request, brand_name=None):
    """Display all products from a specific brand"""
    # Decode URL-encoded brand name and get products
    brand_name = brand_name.replace('-', ' ')
    products = Product.objects.filter(brand__iexact=brand_name)
    
    if not products.exists():
        # If no products found, try to find closest match
        products = Product.objects.filter(brand__icontains=brand_name)
    
    context = {
        'brand': brand_name,
        'products': products,
        'product_count': products.count()
    }
    return render(request, 'store/brand.html', context)

def product_info(request, product_slug):
    product = get_object_or_404(Product, slug=product_slug)
    context = {'product': product}
    return render(request, 'store/product-info.html', context)

def search_products(request):
    query = request.GET.get('q', '')
    is_ajax = request.GET.get('ajax', '') == '1'
    if query:
        products = Product.objects.filter(
            Q(title__icontains=query) | 
            Q(brand__icontains=query) | 
            Q(description__icontains=query)
        ).distinct()[:10]  # Limit to 10 results for AJAX
    else:
        products = Product.objects.none()
    # If this is an AJAX request, return HTML snippet for suggestions
    if is_ajax:
        html = render_to_string('store/search-suggestions.html', {'products': products, 'query': query})
        return HttpResponse(html)
    # Otherwise, return full page
    context = {
        'products': products,
        'query': query,
        'product_count': products.count()
    }
    return render(request, 'store/search-results.html', context)

'''
The Q module is used for advanced Django query. Whereas a 
filter() is used to filter any data, as is here, that would
be title, brand, and description. With Q, it is done by the use
of tranditional filter, with the use of Q(args). The args
would be any of the title, brand and/or description that would 
then be the query variable as it is transalted in their search 
html pages. 

'''