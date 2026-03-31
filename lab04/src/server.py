from http.server import HTTPServer, BaseHTTPRequestHandler
import requests

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        
        response = requests.get('http:/' + self.path)
        self.wfile.write(response.text.encode('utf-8'))

        f = open('logfile.txt', 'a', encoding='utf-8')
        f.write('GET request, path: http:/{}, status code: {}\n'.format(self.path, response.status_code))
        f.close()

httpd = HTTPServer(('localhost', 8000), SimpleHTTPRequestHandler)
print('Listening at http://localhost:8000')
httpd.serve_forever()