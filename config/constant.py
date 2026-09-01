

# Database

GET_DB_TABLE_SCHEMA = """SELECT table_name 
                        FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_type = 'BASE TABLE'
                        ORDER BY table_name;
                      """

GET_DB_COLUMN_SCHEMA = f"""SELECT column_name, data_type, is_nullable
                        FROM information_schema.columns
                        WHERE table_name = %s
                        ORDER BY ordinal_position;"""
