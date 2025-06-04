from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
from flask_pymongo import PyMongo
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from bson import ObjectId
from datetime import datetime
import os
from config import Config

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(Config)

# Profile pictures folder (ensure this is under static for url_for('static', ...))
PROFILE_PICTURES_FOLDER = os.path.join(app.static_folder, 'profile_pictures')
os.makedirs(PROFILE_PICTURES_FOLDER, exist_ok=True)

# Initialize MongoDB
mongo = PyMongo(app)

# Initialize Login Manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# User Model
class User(UserMixin):
    def __init__(self, user_data):
        self.user_data = user_data
        
    def get_id(self):
        return str(self.user_data['_id'])
    
    # Add property accessors
    @property
    def name(self):
        return self.user_data.get('name') or ''
    
    @property
    def email(self):
        return self.user_data.get('email', '')

    @property
    def profile_picture(self):
        return self.user_data.get('profile_picture')

    @property
    def settings(self):
        # Ensure default settings are provided if not in DB
        user_settings = self.user_data.get('settings', {}) # Default to empty dict if 'settings' key is missing
        default_settings = {
            'email_notifications': True,
            'document_reminders': True
        }
        # Merge defaults with user settings; user's explicit settings take precedence.
        return {**default_settings, **user_settings}

@login_manager.user_loader
def load_user(user_id):
    user_data = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    return User(user_data) if user_data else None

# Utility functions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS

# Routes
@app.route('/')
def landing():
    return render_template('landing.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        # Get form data
        name = request.form.get('name')
        email = request.form.get('email')
        aadhar_number = request.form.get('aadhar_number')
        password = request.form.get('password')
        
        # Check if user exists
        if mongo.db.users.find_one({'email': email}):
            flash('Email already registered', 'error')
            return redirect(url_for('register'))
        
        # Create new user
        user = {
            'name': name,
            'email': email,
            'aadhar_number': aadhar_number,
            'password_hash': generate_password_hash(password),
            'profile_picture': '',
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        }
        
        mongo.db.users.insert_one(user)
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
        
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = request.form.get('remember') == 'on'
        
        user_data = mongo.db.users.find_one({'email': email})
        
        if user_data and check_password_hash(user_data['password_hash'], password):
            user = User(user_data)
            login_user(user, remember=remember)
            return redirect(url_for('dashboard'))
            
        flash('Invalid email or password', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('landing'))

@app.route('/dashboard')
@login_required
def dashboard():
    # Get user's document statistics
    total_docs = mongo.db.documents.count_documents({'user_id': ObjectId(current_user.get_id())})
    recent_docs = list(mongo.db.documents.find(
        {'user_id': ObjectId(current_user.get_id())}).sort('upload_date', -1).limit(5))
    
    return render_template('dashboard.html', 
                         total_docs=total_docs,
                         recent_docs=recent_docs)

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        if 'document' not in request.files:
            flash('No file selected', 'error')
            return redirect(request.url)
            
        file = request.files['document']
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(request.url)
            
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            
            # Save document info to database
            doc = {
                'user_id': ObjectId(current_user.get_id()),
                'filename': filename,
                'original_filename': file.filename,
                'file_path': file_path,
                'file_type': filename.rsplit('.', 1)[1].lower(),
                'file_size': os.path.getsize(file_path),
                'category': request.form.get('category'),
                'tags': request.form.get('tags').split(',') if request.form.get('tags') else [],
                'description': request.form.get('description'),
                'upload_date': datetime.utcnow(),
                'last_accessed': datetime.utcnow()
            }
            
            mongo.db.documents.insert_one(doc)
            flash('Document uploaded successfully!', 'success')
            return redirect(url_for('documents'))
            
        flash('Invalid file type', 'error')
    return render_template('upload.html')

@app.route('/documents')
@login_required
def documents():
    # Get filters
    category = request.args.get('category', '')
    sort_by = request.args.get('sort', 'date_desc')
    
    # Build query
    query = {'user_id': ObjectId(current_user.get_id())}
    if category:
        query['category'] = category
    
    # Handle sorting
    sort_options = {
        'date_desc': [('upload_date', -1)],
        'date_asc': [('upload_date', 1)],
        'name_asc': [('original_filename', 1)],
        'name_desc': [('original_filename', -1)],
        'size_desc': [('file_size', -1)],
        'size_asc': [('file_size', 1)]
    }
    
    sort_criteria = sort_options.get(sort_by, [('upload_date', -1)])
    
    # Get documents
    documents = list(mongo.db.documents.find(query).sort(sort_criteria))
    
    return render_template('documents.html', documents=documents)

@app.route('/profile')
@login_required
def profile():
    user_id = ObjectId(current_user.get_id())
    
    # Get statistics
    total_docs = mongo.db.documents.count_documents({'user_id': user_id})
    
    # Calculate storage used
    pipeline = [
        {'$match': {'user_id': user_id}},
        {'$group': {'_id': None, 'total_size': {'$sum': '$file_size'}}}
    ]
    storage_result = list(mongo.db.documents.aggregate(pipeline))
    storage_used = storage_result[0]['total_size'] if storage_result else 0
    storage_used_mb = round(storage_used / (1024 * 1024), 2)
    
    # Get last upload date
    last_doc = mongo.db.documents.find_one(
        {'user_id': user_id}, 
        sort=[('upload_date', -1)]
    )
    last_upload_days = 0
    if last_doc:
        last_upload_days = (datetime.utcnow() - last_doc['upload_date']).days
    
    # Get document categories count
    categories_pipeline = [
        {'$match': {'user_id': user_id}},
        {'$group': {'_id': '$category', 'count': {'$sum': 1}}}
    ]
    categories_result = list(mongo.db.documents.aggregate(categories_pipeline))
    categories = {item['_id']: item['count'] for item in categories_result}
    
    # Get recent activity (last 10 documents)
    recent_docs = list(mongo.db.documents.find(
        {'user_id': user_id}
    ).sort('upload_date', -1).limit(10))
    
    recent_activity = []
    for doc in recent_docs:
        recent_activity.append({
            'type': 'upload',
            'description': f'Uploaded {doc["original_filename"]}',
            'timestamp': doc['upload_date']
        })
    
    stats = {
        'total_documents': total_docs,
        'storage_used': f'{storage_used_mb} MB',
        'last_upload_days': last_upload_days,
        'categories': categories
    }
    
    return render_template('profile.html', 
                         stats=stats, 
                         recent_activity=recent_activity)

@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    user_id = ObjectId(current_user.get_id())
    current_user_data_from_db = mongo.db.users.find_one({'_id': user_id})

    updates = {} 
    made_changes = False

    new_name = request.form.get('name')
    if new_name and new_name != current_user_data_from_db.get('name'):
        updates['name'] = new_name
        made_changes = True

    new_email = request.form.get('email')
    if new_email and new_email != current_user_data_from_db.get('email'):
        if mongo.db.users.find_one({'email': new_email, '_id': {'$ne': user_id}}):
            flash('Email address is already in use by another account.', 'error')
            return redirect(url_for('profile'))
        updates['email'] = new_email
        made_changes = True
    
    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')
    
    if new_password:
        if not current_password:
            flash('Please enter your current password to change it.', 'error')
            return redirect(url_for('profile'))
        if new_password != confirm_password:
            flash('New passwords do not match.', 'error')
            return redirect(url_for('profile'))
        
        if check_password_hash(current_user_data_from_db['password_hash'], current_password):
            updates['password_hash'] = generate_password_hash(new_password)
            made_changes = True
        else:
            flash('Current password is incorrect.', 'error')
            return redirect(url_for('profile'))
    
    current_settings = current_user_data_from_db.get('settings', {
        'email_notifications': True, 'document_reminders': True
    })
    new_settings = {
        'email_notifications': 'email_notifications' in request.form,
        'document_reminders': 'document_reminders' in request.form
    }
    if new_settings != current_settings:
        updates['settings'] = new_settings
        made_changes = True
    
    if 'profile_picture' in request.files:
        file = request.files['profile_picture']
        if file and file.filename != '':
            if allowed_file(file.filename):
                filename_base, file_ext = os.path.splitext(file.filename)
                unique_filename = secure_filename(f"{current_user.get_id()}_{int(datetime.utcnow().timestamp())}{file_ext}")
                
                file_path = os.path.join(PROFILE_PICTURES_FOLDER, unique_filename)
                
                old_picture_filename = current_user_data_from_db.get('profile_picture')
                if old_picture_filename:
                    old_pic_path = os.path.join(PROFILE_PICTURES_FOLDER, old_picture_filename)
                    if os.path.exists(old_pic_path):
                        try:
                            os.remove(old_pic_path)
                        except Exception as e:
                            app.logger.error(f"Error deleting old profile picture {old_pic_path}: {e}")
                
                file.save(file_path)
                updates['profile_picture'] = unique_filename
                made_changes = True
            else:
                flash(f"Invalid file type for profile picture. Allowed types: {', '.join(Config.ALLOWED_EXTENSIONS) if hasattr(Config, 'ALLOWED_EXTENSIONS') else 'configured types'}.", 'error')

    if made_changes:
        updates['updated_at'] = datetime.utcnow()
        mongo.db.users.update_one(
            {'_id': user_id},
            {'$set': updates}
        )
        flash('Profile updated successfully!', 'success')
    elif not ('profile_picture' in request.files and request.files['profile_picture'].filename != ''):
        flash('No changes were made to your profile.', 'info')
        
    return redirect(url_for('profile'))



@app.route('/download/<doc_id>')
@login_required
def download_document(doc_id):
    doc = mongo.db.documents.find_one({'_id': ObjectId(doc_id)})
    if not doc or doc['user_id'] != ObjectId(current_user.get_id()):
        flash('Document not found', 'error')
        return redirect(url_for('documents'))
    
    return send_file(doc['file_path'], as_attachment=True, 
                     download_name=doc['original_filename'])

@app.route('/delete/<doc_id>', methods=['DELETE'])
@login_required
def delete_document_api(doc_id):
    doc = mongo.db.documents.find_one({'_id': ObjectId(doc_id)})
    if not doc or doc['user_id'] != ObjectId(current_user.get_id()):
        return {'error': 'Document not found'}, 404
    
    # Delete file from filesystem
    try:
        os.remove(doc['file_path'])
    except:
        pass
    
    # Delete document from database
    mongo.db.documents.delete_one({'_id': ObjectId(doc_id)})
    return {'success': True}

@app.route('/search')
@login_required
def search():
    query = request.args.get('q', '')
    category = request.args.get('category')
    file_type = request.args.get('file_type')
    date_range = request.args.get('date_range')
    
    # Build search query
    search_query = {'user_id': ObjectId(current_user.get_id())}
    
    if query:
        search_query['$or'] = [
            {'original_filename': {'$regex': query, '$options': 'i'}},
            {'description': {'$regex': query, '$options': 'i'}},
            {'tags': {'$regex': query, '$options': 'i'}}
        ]
    
    if category:
        search_query['category'] = category
    
    if file_type:
        search_query['file_type'] = file_type
    
    if date_range:
        try:
            days = int(date_range)
            date_threshold = datetime.utcnow() - timedelta(days=days)
            search_query['upload_date'] = {'$gte': date_threshold}
        except ValueError:
            pass
    
    # Execute search
    results = list(mongo.db.documents.find(search_query).sort('upload_date', -1))
    
    # Get unique categories for filter
    categories = mongo.db.documents.distinct('category', {'user_id': ObjectId(current_user.get_id())})
    
    return render_template('search.html',
                          results=results,
                          query=query,
                          categories=categories,
                          selected_category=category,
                          selected_file_type=file_type,
                          selected_date_range=date_range)

    # Build search query
    search_query = {'user_id': ObjectId(current_user.get_id())}
    if query:
        search_query['$or'] = [
            {'filename': {'$regex': query, '$options': 'i'}},
            {'description': {'$regex': query, '$options': 'i'}},
            {'tags': {'$regex': query, '$options': 'i'}}
        ]
    if category:
        search_query['category'] = category
    if file_type:
        search_query['file_type'] = file_type
    if date_from or date_to:
        date_query = {}
        if date_from:
            date_query['$gte'] = datetime.strptime(date_from, '%Y-%m-%d')
        if date_to:
            date_query['$lte'] = datetime.strptime(date_to, '%Y-%m-%d')
        search_query['upload_date'] = date_query
    
    results = list(mongo.db.documents.find(search_query))
    return render_template('search.html', results=results, query=query)

@app.route('/document/<doc_id>')
@login_required
def view_document(doc_id):
    doc = mongo.db.documents.find_one({'_id': ObjectId(doc_id)})
    if not doc or doc['user_id'] != ObjectId(current_user.get_id()):
        flash('Document not found', 'error')
        return redirect(url_for('documents'))
    
    # Update last accessed time
    mongo.db.documents.update_one(
        {'_id': ObjectId(doc_id)},
        {'$set': {'last_accessed': datetime.utcnow()}}
    )
    
    return send_file(doc['file_path'])

@app.route('/delete/<doc_id>')
@login_required
def delete_document(doc_id):
    doc = mongo.db.documents.find_one({'_id': ObjectId(doc_id)})
    if not doc or doc['user_id'] != ObjectId(current_user.get_id()):
        flash('Document not found', 'error')
        return redirect(url_for('documents'))
    
    # Delete file from filesystem
    try:
        os.remove(doc['file_path'])
    except:
        pass
    
    # Delete document from database
    mongo.db.documents.delete_one({'_id': ObjectId(doc_id)})
    flash('Document deleted successfully!', 'success')
    return redirect(url_for('documents'))

if __name__ == '__main__':
    # Create upload folder if it doesn't exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'profiles'), exist_ok=True)
    app.run(debug=True)