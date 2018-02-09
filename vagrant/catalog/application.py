from flask import Flask, render_template, request, redirect, url_for, abort, jsonify
from flask import session as login_session
from flask import make_response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError
from db_setup import Base, Category, CatalogItem
import random, string, json, requests
app = Flask(__name__)

engine = create_engine('postgresql:///catalog')
Base.metadata.bind = engine

DBSession = sessionmaker(bind=engine)
session = DBSession()

CLIENT_ID = json.load(open('client_secret.json', 'r'))['web']['client_id']

@app.route('/login')
def showLogin():
    state = ''.join(random.choice(string.ascii_uppercase + string.digits) for x in xrange(32))
    login_session['state'] = state
    return render_template('login.html', state=state)

@app.route('/gconnect', methods=['POST'])
def gconnect():
    # validate state token
    if request.args.get('state') != login_session['state']:
        return jsonify('Invalid state'), 401
    # obtain auth code
    code = request.data

    try:
        # update the auth code into a creds object
        oauth_flow = flow_from_clientsecrets('client_secret.json', scope='', redirect_uri='postmessage')
        creds = oauth_flow.step2_exchange(code)
    except FlowExchangeError:
        return jsonify('Failed to upgrade the auth code'), 401
    
    # validate access token
    access_token = creds.access_token
    url = 'https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s' % access_token
    result = requests.get(url).json()
    # abort if error found
    if result.get('error'):
        return jsonify(result.get('error')), 500
    
    # verify access is for intended user
    gplus_id = creds.id_token.get('sub')
    if result.get('user_id') != gplus_id:
        return jsonify('Invalid token.'), 401
    
    # verify token is for this app
    if result.get('issued_to') != CLIENT_ID:
        return jsonify('Invalid token.'), 401
    
    stored_access_token = login_session.get('access_token')
    stored_gplus_id = login_session.get('gplus_id')
    if stored_access_token and gplus_id == stored_gplus_id:
        return 'Welcome back %s, please wait...' % login_session['name']
    
    login_session['access_token'] = creds.access_token
    login_session['gplus_id'] = gplus_id

    # Get user info
    userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    params = {'access_token': creds.access_token, 'alt': 'json'}
    data = requests.get(userinfo_url, params=params).json()
    login_session['name'] = data['name']
    login_session['picture'] = data['picture']
    login_session['email'] = data['email']

    return 'Welcome %s, please wait...' % login_session['name']

@app.route('/logout')
@app.route('/gdisconnect')
def gdisconnect():
    access_token = login_session.get('access_token')
    if not access_token:
        return 'No Access token found', 401
    print 'Token to be disconnected: %s' % access_token
    print 'For %s' % login_session['name']
    url = 'https://accounts.google.com/o/oauth2/revoke?token=%s' % login_session['access_token']
    r = requests.get(url)
    print r.status_code
    if r.ok:
        del login_session['access_token']
        del login_session['gplus_id']
        del login_session['name']
        del login_session['email']
        del login_session['picture']
        return jsonify('Successfully disconnected')
    else:
        return jsonify('Failed to revoke token'), 400

@app.route('/')
@app.route('/categories/')
def homepage():
    categories = session.query(Category).all()
    items = session.query(CatalogItem).order_by(CatalogItem.id.desc()).limit(3)
    return render_template('homepage.html', categories=categories, items=items)

@app.route('/categories/<int:category_id>/update/', methods=['GET', 'POST'])
def updateCategory(category_id):
    categories = session.query(Category)
    selected_category = categories.filter_by(id=category_id)
    if not selected_category.one_or_none():
        abort(404)
    elif request.method == 'POST':
        category = request.form.get('category') or selected_category.one_or_none().category
        selected_category.update({'category': category})
        session.commit()
        return redirect(url_for('showCategory', category_id=selected_category.one_or_none().id))
    else:
        return render_template('update-category.html', categories=categories, selected_category=selected_category.one_or_none())

@app.route('/categories/<int:category_id>/delete/', methods=['GET', 'POST'])
def deleteCategory(category_id):
    categories = session.query(Category)
    selected_category = categories.filter_by(id=category_id)
    category_items = session.query(CatalogItem).filter_by(id=category_id).all()
    if not selected_category.one_or_none():
        abort(404)
    if len(category_items):
        abort(400)
    elif request.method == 'POST':
        selected_category.delete()
        session.commit()
        return redirect(url_for('homepage'))
    else:
        return render_template('delete-category.html', categories=categories.all(), selected_category=selected_category.one_or_none())

@app.route('/categories/<int:category_id>/')
@app.route('/categories/<int:category_id>/items/')
def showCategory(category_id):
    categories = session.query(Category)
    category = categories.filter_by(id=category_id).one_or_none()
    if not category:
        abort(404)
    category_items = session.query(CatalogItem).filter_by(category=category).all()
    return render_template('category-items.html', categories=categories.all(), selected_category=category, category_items=category_items)

@app.route('/items/new/', methods=['GET', 'POST'])
def createItem():
    categories = session.query(Category).all()
    if request.method == 'POST':
        item_name = request.form.get('item_name') or abort(400)
        description = request.form.get('description')
        category = request.form.get('category') or abort(400)
        category_id = session.query(Category.id).filter_by(category=category).one_or_none()
        if not category_id:
            new_category = Category(category=category)
            session.add(new_category)
            session.commit()
            category_id = new_category.id
        new_item = CatalogItem(item_name=item_name, description=description, category_id=category_id)
        session.add(new_item)
        session.commit()
        return redirect(url_for('showItem', item_id=new_item.id))
    else:
        return render_template('new-item.html', categories=categories)

@app.route('/items/<int:item_id>/update/', methods=['GET', 'POST'])
def updateItem(item_id):
    categories = session.query(Category).all()
    selected_item = session.query(CatalogItem).filter_by(id=item_id)
    if not selected_item.one_or_none():
        abort(404)
    elif request.method == 'POST':
        item_name = request.form.get('item_name') or selected_item.one_or_none().item_name
        description = request.form.get('description')
        category = request.form.get('category') or selected_item.one_or_none().category
        category_id = session.query(Category.id).filter_by(category=category).one_or_none()
        if not category_id:
            new_category = Category(category=category)
            session.add(new_category)
            session.commit()
            category_id = new_category.id
        selected_item.update({'item_name': item_name, 'description': description, 'category_id': category_id})
        session.commit()
        return redirect(url_for('showItem', item_id=selected_item.one_or_none().id))
    else:
        return render_template('update-item.html', categories=categories, selected_item=selected_item.one_or_none())

@app.route('/items/<int:item_id>/delete/', methods=['GET', 'POST'])
def deleteItem(item_id):
    categories = session.query(Category).all()
    selected_item = session.query(CatalogItem).filter_by(id=item_id)
    if not selected_item.one_or_none():
        abort(404)
    elif request.method == 'POST':
        selected_item.delete()
        session.commit()
        return redirect(url_for('homepage'))
    else:
        return render_template('delete-item.html', categories=categories, selected_item=selected_item.one_or_none())

@app.route('/items/<int:item_id>/')
def showItem(item_id):
    categories = session.query(Category).all()
    selected_item = session.query(CatalogItem).filter_by(id=item_id).one_or_none()
    if not selected_item:
        abort(404)
    return render_template('show-item.html', categories=categories, selected_item=selected_item)

@app.route('/api/categories/')
def categoriesApi():
    categories = session.query(Category).order_by(Category.id).all()
    return jsonify([c.serialize for c in categories])

@app.route('/api/items/')
def itemsApi():
    items = session.query(CatalogItem).order_by(CatalogItem.id).all()
    return jsonify([i.serialize for i in items])

if __name__ == '__main__':
    app.debug = True
    app.secret_key = 'b\x0b\xab\x91(\x92j.15\xd5\xebG\x01aTD\x9c\x11\xe8KP\x01r'
    app.run(host = '0.0.0.0', port = 5000)