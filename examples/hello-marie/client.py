from marie import Client, DocumentArray

if __name__ == '__main__':
    # c = Client(host='grpc://0.0.0.0:54321')
    c = Client(host='http://0.0.0.0:54321')
    da = c.post('/', DocumentArray.empty(2))
    print(da.texts)

    da = c.post('/crunch-numbers-aa', DocumentArray.empty(2))
    print(da.texts)

    da = c.post('/crunch-numbers-xx', DocumentArray.empty(2))
    print(da.texts)
